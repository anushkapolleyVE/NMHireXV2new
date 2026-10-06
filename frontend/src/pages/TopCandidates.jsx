import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Header from '../components/Header';
import { createJobFromRequisition, fetchTopCandidates, updateCandidateStatus, getJobCandidates } from '../utils/api';

function WhatsappInviteModal({ isOpen, onClose, candidate, onSend }) {
  if (!isOpen || !candidate) return null;

  const devStage = import.meta.env.VITE_HIRE_X_DEV_STAGE || 'production';
  const stageNumber = import.meta.env.VITE_WHATSAPP_STAGE_NUMBER || '';
  const isStageMode = devStage !== 'production';

  const roleText = candidate.current_role || candidate.job || '';
  const companyText = candidate.current_company ? `@ ${candidate.current_company}` : '';
  const locationText = candidate.location ? `- ${candidate.location}` : '';
  const subtitleArr = [];
  if (roleText) subtitleArr.push(roleText);
  if (companyText) subtitleArr.push(companyText);
  if (locationText) subtitleArr.push(locationText);
  const subtitleFinal = subtitleArr.join(' ');

  const handleSend = async () => {
    if (candidate.phone) {
      if (onSend) {
        const targetPhone = isStageMode ? stageNumber : candidate.phone;
        await onSend(candidate, targetPhone);
      }
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-[24px] bg-white p-6 shadow-2xl relative animate-in fade-in zoom-in-95 duration-200">
        <div className="flex gap-4 items-start mb-6">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-green-50 text-green-500">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
          </div>
          <div className="pt-1 text-left">
            <h2 className="text-xl font-bold text-slate-800">Send WhatsApp invite</h2>
            <p className="mt-1 text-sm text-slate-500">Confirm the number before it goes out.</p>
          </div>
        </div>

        <div className="mb-4 rounded-2xl bg-[#F3F5F9] p-5 text-left">
          <h3 className="text-lg font-bold text-slate-800">{candidate.name || 'Unnamed Candidate'}</h3>
          {subtitleFinal && <p className="mt-1 text-sm font-medium text-slate-500">{subtitleFinal}</p>}
          <p className="mt-4 text-sm font-medium text-slate-500">Candidate's number: {candidate.phone || 'No phone number'}</p>
        </div>

        {isStageMode && (
          <div className="mb-6 rounded-2xl bg-[#FFFBF0] p-5 border border-[#FDE68A] text-left">
            <p className="text-[11px] font-bold uppercase tracking-widest text-[#B45309] mb-2">STAGE MODE — ACTUALLY SENDING TO</p>
            <p className="text-xl font-bold text-[#92400E] mb-4">{stageNumber}</p>
            <p className="text-sm font-medium text-[#B45309] leading-relaxed">
              {candidate.name || 'Candidate'} receives nothing. Set <code>HIRE_X_DEV_STAGE=production</code> to contact candidates for real.
            </p>
          </div>
        )}

        <div className="flex justify-end gap-3 mt-8">
          <button
            onClick={onClose}
            className="rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-sm font-bold text-slate-700 transition-colors hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSend}
            disabled={!candidate.phone}
            className="rounded-xl bg-green-500 px-5 py-2.5 text-sm font-bold text-white transition-colors hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Send invite
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TopCandidates() {
  const { vereq } = useParams();
  const navigate = useNavigate();
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [statusText, setStatusText] = useState('Creating job from requisition...');
  
  const [jobId, setJobId] = useState(null);
  const [whatsappModalOpen, setWhatsappModalOpen] = useState(false);
  const [selectedWhatsappCandidate, setSelectedWhatsappCandidate] = useState(null);
  const [whatsappContacted, setWhatsappContacted] = useState({});

  const handleWhatsappOutreach = async (candidate, targetPhone) => {
    try {
      if (!jobId) throw new Error("Job ID not available");
      const cId = candidate.candidate_id || candidate.id;
      await updateCandidateStatus(jobId, cId, 'CONTACTED', targetPhone);
      setWhatsappContacted(prev => ({ ...prev, [cId]: true }));
      console.log('WhatsApp message sent to candidate:', candidate.name);
    } catch (err) {
      console.error('Failed to send WhatsApp message', err);
      alert('Failed to send WhatsApp message. Please try again.');
    }
  };

  useEffect(() => {
    let isMounted = true;
    const fetchCandidates = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // 1. Create job from requisition
        setStatusText('Creating job from requisition...');
        const jobData = await createJobFromRequisition(vereq);
        const jId = jobData.job_id;
        if (isMounted) setJobId(jId);

        // 2. Check if we already have candidates for this job
        setStatusText('Checking local database...');
        try {
          const localData = await getJobCandidates(jId);
          let localList = [];
          if (Array.isArray(localData)) localList = localData;
          else if (localData && Array.isArray(localData.data)) localList = localData.data;

          if (localList.length > 0) {
            if (isMounted) {
              setCandidates(localList);
              setLoading(false);
            }
            return; // Skip external screening since candidates are already here
          }
        } catch (e) {
          console.warn("Failed to fetch local candidates, proceeding with screening", e);
        }

        // 3. Fetch top candidates
        setStatusText('Sheela is starting to read resumes...');
        
        const loadingMessages = [
          "Analyzing candidate skills...",
          "Extracting domain experience...",
          "Comparing candidates against the JD...",
          "Ranking the best matches...",
          "Almost there, finalizing scores..."
        ];
        let msgIndex = 0;
        const intervalId = setInterval(() => {
          setStatusText(loadingMessages[msgIndex]);
          msgIndex = (msgIndex + 1) % loadingMessages.length;
        }, 4000);

        try {
          const matchData = await fetchTopCandidates(jId, vereq);
          clearInterval(intervalId);
          
          if (isMounted) {
            const apiData = matchData.data || matchData;
            let candidatesList = [];
            
            if (Array.isArray(apiData)) {
              candidatesList = apiData;
            } else if (apiData && Array.isArray(apiData.candidates)) {
              candidatesList = apiData.candidates;
            } else if (apiData && Array.isArray(apiData.matches)) {
              candidatesList = apiData.matches;
            } else if (apiData && Array.isArray(apiData.items)) {
              candidatesList = apiData.items;
            } else if (apiData && Array.isArray(apiData.data)) {
              candidatesList = apiData.data;
            } else if (apiData && Array.isArray(apiData.results)) {
              candidatesList = apiData.results;
            }

            setCandidates(candidatesList);
            setLoading(false);
          }
        } catch (fetchErr) {
          clearInterval(intervalId);
          throw fetchErr;
        }
      } catch (err) {
        if (isMounted) {
          console.error(err);
          setError(err.message || 'Failed to fetch top candidates');
          setLoading(false);
        }
      }
    };
    
    if (vereq) {
      fetchCandidates();
    }
    
    return () => { isMounted = false; };
  }, [vereq]);

  return (
    <div className="relative min-h-screen w-full overflow-hidden antialiased pb-20">
      <div className="glow-bg top-[-30%] left-[-20%] animate-pulse-slow"></div>
      <div className="glow-bg bottom-[-20%] right-[-10%] animate-pulse-slow"
        style={{ animationDelay: '2s', background: 'radial-gradient(circle, rgba(20,184,166,0.1) 0%, rgba(59,130,246,0.05) 40%, rgba(2,6,23,0) 70%)' }}
      ></div>

      <Header />
      
      <WhatsappInviteModal
        isOpen={whatsappModalOpen}
        onClose={() => setWhatsappModalOpen(false)}
        candidate={selectedWhatsappCandidate}
        onSend={handleWhatsappOutreach}
      />

      <main className="relative z-10">
        <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
          <button 
            onClick={() => navigate('/job-descriptions')}
            className="mb-6 inline-flex items-center text-sm font-medium text-slate-400 hover:text-white transition-colors"
          >
            &larr; Back to JDs
          </button>
          
          <div className="mb-10 flex flex-col sm:flex-row justify-between items-start gap-4 animate-slide-up opacity-0-init animate-delay-100">
            <div>
              <div className="mb-2 inline-flex items-center gap-2.5 rounded-full bg-slate-800/80 px-3 py-1.5 ring-1 ring-slate-700 w-max">
                <span className="size-2 rounded-full bg-accent shadow-[0_0_10px_rgba(20,184,166,0.8)]"></span>
                <p className="text-xs font-bold uppercase tracking-[0.15em] text-slate-300">Top Matches</p>
              </div>
              <h1 className="font-display text-4xl font-bold tracking-tight sm:text-5xl text-white">Candidates for {vereq}</h1>
              <p className="text-base text-slate-400">Review the top 30 candidates matched for this requisition.</p>
            </div>
          </div>

          <div className="glass-dark rounded-[24px] overflow-hidden animate-slide-up opacity-0-init animate-delay-300 border border-slate-800/50">
            <div className="overflow-auto max-h-[600px] custom-scrollbar pb-2 pr-1 relative">
              <table className="w-full min-w-[960px] text-left border-collapse">
                <thead className="sticky top-0 bg-[#0B1121] z-10 before:absolute before:inset-0 before:bg-slate-900/50 before:-z-10 before:backdrop-blur-md">
                  <tr className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    <th className="py-4 pl-6 border-b border-slate-700">Candidate</th>
                    <th className="py-4 border-b border-slate-700">Email / Phone</th>
                    <th className="py-4 border-b border-slate-700">Classification</th>
                    <th className="py-4 border-b border-slate-700">Score</th>
                    <th className="py-4 pr-6 text-right border-b border-slate-700">Resume</th>
                  </tr>
                </thead>
                <tbody className="text-sm">
                  {loading ? (
                    <tr><td colSpan="5" className="py-12 text-center">
                      <div className="inline-flex flex-col items-center gap-3 text-slate-400">
                        <svg className="w-8 h-8 animate-spin text-accent" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeDasharray="30 60" className="opacity-75"></circle>
                        </svg>
                        <span>{statusText}</span>
                      </div>
                    </td></tr>
                  ) : error ? (
                    <tr><td colSpan="5" className="py-12 text-center text-red-400">
                      Error: {error}
                    </td></tr>
                  ) : candidates.length === 0 ? (
                    <tr><td colSpan="5" className="py-12 text-center text-slate-500">
                      No candidates found for this requisition.
                    </td></tr>
                  ) : (
                    candidates.slice(0, 30).map((c, index) => (
                      <tr key={c.id || index} className="table-row-hover border-b border-slate-800/50 group">
                        <td className="py-5 pl-6">
                          <p className="font-bold text-white text-base">{c.name || 'Unknown Name'}</p>
                        </td>
                        <td className="py-5">
                          {c.email && <p className="font-medium text-slate-300">{c.email}</p>}
                          {c.phone && <p className="text-[11px] text-slate-500">{c.phone}</p>}
                        </td>
                        <td className="py-5">
                          <span className={`inline-flex rounded-full px-3 py-1 text-[11px] font-bold ring-1 w-max ${c.classification === 'GOOD_FIT' ? 'bg-teal-500/20 text-teal-300 ring-teal-500/30' : 'bg-slate-500/20 text-slate-300 ring-slate-500/30'}`}>
                            {c.classification || 'N/A'}
                          </span>
                        </td>
                        <td className="py-5">
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-24 bg-slate-800 rounded-full overflow-hidden">
                              <div className="h-full bg-accent" style={{ width: `${Math.min(100, Math.max(0, c.score || 0))}%` }}></div>
                            </div>
                            <span className="text-xs font-bold text-white">{Number(c.score || 0).toFixed(0)}</span>
                          </div>
                        </td>
                        <td className="py-5 pr-6 text-right">
                          <div className="flex justify-end items-center gap-2">
                            {c.resume_url && (
                              <a 
                                href={c.resume_url} 
                                target="_blank" 
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-3 py-1.5 text-xs font-bold text-white shadow-sm ring-1 ring-slate-700 hover:bg-slate-700 transition-colors"
                              >
                                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                </svg>
                                Resume
                              </a>
                            )}
                            <button
                              onClick={() => {
                                setSelectedWhatsappCandidate(c);
                                setWhatsappModalOpen(true);
                              }}
                              disabled={whatsappContacted[c.candidate_id || c.id] || c.status === 'CONTACTED'}
                              className={`inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-bold transition-colors ${
                                (whatsappContacted[c.candidate_id || c.id] || c.status === 'CONTACTED')
                                  ? 'bg-green-500/20 text-green-500 border border-green-500/30'
                                  : 'bg-green-600 text-white hover:bg-green-500 shadow-sm'
                              }`}
                            >
                              {(whatsappContacted[c.candidate_id || c.id] || c.status === 'CONTACTED') ? "✓ Invited" : "WhatsApp"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
