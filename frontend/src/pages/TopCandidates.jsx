import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Header from '../components/Header';
import {
  createJobFromRequisition,
  fetchTopCandidates,
  updateCandidateStatus,
  bulkUpdateCandidateStatus,
  getJobCandidates,
} from '../utils/api';

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

function BulkWhatsappInviteModal({
  isOpen,
  onClose,
  selectedCandidates,
  onSendBulk,
}) {
  const [isSending, setIsSending] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0, currentName: '' });
  const [result, setResult] = useState(null);

  if (!isOpen) return null;

  const devStage = import.meta.env.VITE_HIRE_X_DEV_STAGE || 'production';
  const stageNumber = import.meta.env.VITE_WHATSAPP_STAGE_NUMBER || '';
  const isStageMode = devStage !== 'production';

  const total = selectedCandidates.length;

  const handleStartSending = async () => {
    setIsSending(true);
    setProgress({ current: 0, total, currentName: 'Initializing bulk outreach...' });
    setResult(null);

    try {
      const summary = await onSendBulk((current, totalCount, currentName) => {
        setProgress({ current, total: totalCount, currentName });
      });
      setResult(summary || { sent: total, failed: 0 });
    } catch (err) {
      console.error('Bulk sending failed:', err);
      setResult({ sent: 0, failed: total, error: err.message });
    } finally {
      setIsSending(false);
    }
  };

  const handleClose = () => {
    if (isSending) return;
    setResult(null);
    setProgress({ current: 0, total: 0, currentName: '' });
    onClose();
  };

  const progressPercent = total > 0 ? Math.min(100, Math.round((progress.current / total) * 100)) : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-md">
      <div className="w-full max-w-lg rounded-[28px] bg-[#0F172A] p-7 shadow-2xl border border-slate-700/80 relative animate-in fade-in zoom-in-95 duration-200 text-white">
        
        {/* Modal Header */}
        <div className="flex gap-4 items-start mb-6">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-green-500/10 text-green-400 border border-green-500/20">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
            </svg>
          </div>
          <div className="pt-1 text-left flex-1">
            <h2 className="text-xl font-bold text-white">Send Bulk WhatsApp Invites</h2>
            <p className="mt-1 text-xs text-slate-400">
              {result
                ? "Outreach process finished"
                : isSending
                ? "Dispatching WhatsApp interview invites in real-time"
                : `Dispatch WhatsApp invitations to ${total} selected candidate${total !== 1 ? 's' : ''}.`
              }
            </p>
          </div>
        </div>

        {/* Completion Result Screen */}
        {result ? (
          <div className="space-y-6 animate-in fade-in">
            <div className="rounded-2xl bg-emerald-500/10 border border-emerald-500/30 p-6 text-center">
              <div className="mx-auto w-12 h-12 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 mb-3">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 className="text-lg font-bold text-white mb-1">Bulk Outreach Complete!</h3>
              <p className="text-sm text-emerald-300">
                Successfully sent <span className="font-bold text-white">{result.sent}</span> WhatsApp invite{result.sent !== 1 ? 's' : ''}.
              </p>
              {result.failed > 0 && (
                <p className="text-xs text-red-400 mt-2 font-medium">
                  {result.failed} candidate{result.failed !== 1 ? 's' : ''} could not be delivered.
                </p>
              )}
            </div>

            <div className="flex justify-end">
              <button
                onClick={handleClose}
                className="w-full sm:w-auto rounded-xl bg-accent px-6 py-2.5 text-sm font-bold text-white hover:bg-teal-400 transition-colors shadow-lg cursor-pointer"
              >
                Done
              </button>
            </div>
          </div>
        ) : isSending ? (
          /* Active Progress Screen */
          <div className="space-y-6 animate-in fade-in">
            <div className="rounded-2xl bg-slate-900/80 border border-slate-800 p-5 space-y-4">
              <div className="flex justify-between items-center text-sm font-semibold">
                <span className="text-slate-300">Sending invites...</span>
                <span className="text-green-400 font-mono">{progress.current} / {total} ({progressPercent}%)</span>
              </div>

              {/* Animated Progress Bar */}
              <div className="w-full bg-slate-800 rounded-full h-3 overflow-hidden border border-slate-700/80">
                <div 
                  className="h-full bg-gradient-to-r from-emerald-500 to-green-400 transition-all duration-300 rounded-full shadow-[0_0_12px_rgba(34,197,94,0.5)]"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>

              <p className="text-xs text-slate-400 truncate text-left">
                Current: <span className="text-slate-200 font-medium">{progress.currentName || 'Sending...'}</span>
              </p>
            </div>

            <p className="text-xs text-slate-500 text-center animate-pulse">
              Please do not close this window while messages are being dispatched...
            </p>
          </div>
        ) : (
          /* Initial Confirmation Screen */
          <div className="space-y-5">
            {isStageMode && (
              <div className="rounded-2xl bg-amber-500/10 border border-amber-500/30 p-4 text-left">
                <p className="text-[10px] font-bold uppercase tracking-widest text-amber-400 mb-1">
                  STAGE MODE ACTIVE — ROUTING ALL TO:
                </p>
                <p className="text-base font-bold text-amber-300 font-mono">{stageNumber}</p>
                <p className="text-xs text-amber-300/80 mt-1">
                  Candidates' real phone numbers will not be messaged. Set <code>HIRE_X_DEV_STAGE=production</code> for real candidate outreach.
                </p>
              </div>
            )}

            <div className="text-left">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Selected Candidates ({total})
                </p>
                <span className="text-[11px] text-teal-400 font-semibold bg-teal-500/10 px-2 py-0.5 rounded-full border border-teal-500/20">
                  Ready to invite
                </span>
              </div>
              
              <div className="max-h-48 overflow-y-auto custom-scrollbar rounded-2xl bg-slate-900/60 border border-slate-800 p-2.5 space-y-1.5">
                {selectedCandidates.map((c, i) => (
                  <div key={c.candidate_id || c.id || i} className="flex items-center justify-between text-xs px-3 py-2 rounded-xl bg-slate-800/40 border border-slate-700/30 hover:border-slate-600/50 transition-colors">
                    <div className="flex items-center gap-2.5 truncate">
                      <span className="size-5 rounded-full bg-slate-700/80 text-[10px] font-mono text-slate-300 flex items-center justify-center shrink-0">
                        {i + 1}
                      </span>
                      <span className="font-semibold text-white truncate">{c.name || 'Unnamed'}</span>
                      <span className="text-[11px] text-slate-400 font-mono hidden sm:inline">{c.phone}</span>
                    </div>
                    <span className="text-teal-400 font-bold bg-teal-500/10 px-2 py-0.5 rounded text-[11px] shrink-0 border border-teal-500/20">
                      {Number(c.score || 0).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <p className="text-xs text-slate-400 text-left leading-relaxed">
              Each selected candidate will receive an official WhatsApp invitation message asking them to schedule an interview for this JD.
            </p>

            <div className="flex justify-end gap-3 pt-3">
              <button
                onClick={handleClose}
                className="rounded-xl border border-slate-700 bg-slate-800/80 px-5 py-2.5 text-sm font-bold text-slate-300 transition-colors hover:bg-slate-700 hover:text-white cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleStartSending}
                disabled={total === 0}
                className="rounded-xl bg-gradient-to-r from-emerald-600 to-green-600 px-6 py-2.5 text-sm font-bold text-white transition-all hover:from-emerald-500 hover:to-green-500 shadow-[0_0_15px_rgba(34,197,94,0.35)] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                Send {total} Invites
              </button>
            </div>
          </div>
        )}

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
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [selectedWhatsappCandidate, setSelectedWhatsappCandidate] = useState(null);
  const [whatsappContacted, setWhatsappContacted] = useState({});
  const [selectedIds, setSelectedIds] = useState([]);

  // Compute top 30
  const top30 = candidates.slice(0, 30);

  const isCandidateInvited = (c) => {
    const cId = c.candidate_id || c.id;
    return Boolean(whatsappContacted[cId] || c.status === 'CONTACTED' || c.recruitment_status === 'CONTACTED');
  };

  const hasCandidatePhone = (c) => {
    return Boolean(c.phone && c.phone !== '-' && String(c.phone).trim() !== '');
  };

  // Eligible for inviting: has phone number and not yet invited
  const eligibleCandidates = top30.filter(c => hasCandidatePhone(c) && !isCandidateInvited(c));
  const isAllSelected = eligibleCandidates.length > 0 && eligibleCandidates.every(c => selectedIds.includes(c.candidate_id || c.id));

  const autoSelectEligible = (list) => {
    const eligible = list.slice(0, 30)
      .filter(c => {
        const cId = c.candidate_id || c.id;
        const isInvited = whatsappContacted[cId] || c.status === 'CONTACTED' || c.recruitment_status === 'CONTACTED';
        const hasPhone = c.phone && c.phone !== '-' && String(c.phone).trim() !== '';
        return hasPhone && !isInvited;
      })
      .map(c => c.candidate_id || c.id);
    setSelectedIds(eligible);
  };

  const handleToggleSelectAll = () => {
    if (isAllSelected) {
      setSelectedIds([]);
    } else {
      setSelectedIds(eligibleCandidates.map(c => c.candidate_id || c.id));
    }
  };

  const handleToggleSelect = (candidateId) => {
    setSelectedIds(prev =>
      prev.includes(candidateId)
        ? prev.filter(id => id !== candidateId)
        : [...prev, candidateId]
    );
  };

  const handleWhatsappOutreach = async (candidate, targetPhone) => {
    try {
      if (!jobId) throw new Error("Job ID not available");
      const cId = candidate.candidate_id || candidate.id;
      await updateCandidateStatus(jobId, cId, 'CONTACTED', targetPhone);
      setWhatsappContacted(prev => ({ ...prev, [cId]: true }));
      setSelectedIds(prev => prev.filter(id => id !== cId));
      console.log('WhatsApp message sent to candidate:', candidate.name);
    } catch (err) {
      console.error('Failed to send WhatsApp message', err);
      alert('Failed to send WhatsApp message. Please try again.');
    }
  };

  const handleBulkOutreach = async (onProgress) => {
    try {
      if (!jobId) throw new Error("Job ID not available");
      const candidatesToSend = top30.filter(c => selectedIds.includes(c.candidate_id || c.id));
      const total = candidatesToSend.length;
      if (total === 0) return { sent: 0, failed: 0 };

      const devStage = import.meta.env.VITE_HIRE_X_DEV_STAGE || 'production';
      const stageNumber = import.meta.env.VITE_WHATSAPP_STAGE_NUMBER || '';
      const isStageMode = devStage !== 'production';

      let sentCount = 0;
      let failedCount = 0;

      // 1. Try dedicated bulk backend endpoint first
      try {
        const cIds = candidatesToSend.map(c => c.candidate_id || c.id);
        const targetPhone = isStageMode ? stageNumber : null;
        if (onProgress) onProgress(1, total, `Batch processing ${total} invites...`);

        const res = await bulkUpdateCandidateStatus(jobId, cIds, 'CONTACTED', targetPhone);
        if (res && res.data) {
          const successIds = (res.data.results || [])
            .filter(r => r.status === 'SUCCESS')
            .map(r => r.candidate_id);

          setWhatsappContacted(prev => {
            const next = { ...prev };
            successIds.forEach(id => { next[id] = true; });
            return next;
          });
          setSelectedIds(prev => prev.filter(id => !successIds.includes(id)));
          return { sent: res.data.sent ?? successIds.length, failed: res.data.failed ?? 0 };
        }
      } catch (bulkErr) {
        console.warn("Bulk API unavailable or failed, falling back to batch sequence:", bulkErr);
      }

      // 2. Fallback: Sequential batch dispatch with live progress updates
      for (let i = 0; i < candidatesToSend.length; i++) {
        const candidate = candidatesToSend[i];
        const cId = candidate.candidate_id || candidate.id;
        const targetPhone = isStageMode ? stageNumber : candidate.phone;

        if (onProgress) {
          onProgress(i + 1, total, candidate.name || `Candidate ${i + 1}`);
        }

        try {
          await updateCandidateStatus(jobId, cId, 'CONTACTED', targetPhone);
          setWhatsappContacted(prev => ({ ...prev, [cId]: true }));
          setSelectedIds(prev => prev.filter(id => id !== cId));
          sentCount++;
        } catch (err) {
          console.error(`Failed to send invite to ${candidate.name}:`, err);
          failedCount++;
        }
      }

      return { sent: sentCount, failed: failedCount };
    } catch (err) {
      console.error("Bulk outreach error:", err);
      throw err;
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
              autoSelectEligible(localList);
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
            autoSelectEligible(candidatesList);
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
      
      {/* Individual Invite Modal */}
      <WhatsappInviteModal
        isOpen={whatsappModalOpen}
        onClose={() => setWhatsappModalOpen(false)}
        candidate={selectedWhatsappCandidate}
        onSend={handleWhatsappOutreach}
      />

      {/* Bulk Invite Modal */}
      <BulkWhatsappInviteModal
        isOpen={bulkModalOpen}
        onClose={() => setBulkModalOpen(false)}
        selectedCandidates={top30.filter(c => selectedIds.includes(c.candidate_id || c.id))}
        onSendBulk={handleBulkOutreach}
      />

      <main className="relative z-10">
        <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
          <button 
            onClick={() => navigate('/job-descriptions')}
            className="mb-6 inline-flex items-center text-sm font-medium text-slate-400 hover:text-white transition-colors cursor-pointer"
          >
            &larr; Back to JDs
          </button>
          
          <div className="mb-10 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 animate-slide-up opacity-0-init animate-delay-100">
            <div>
              <div className="mb-2 inline-flex items-center gap-2.5 rounded-full bg-slate-800/80 px-3 py-1.5 ring-1 ring-slate-700 w-max">
                <span className="size-2 rounded-full bg-accent shadow-[0_0_10px_rgba(20,184,166,0.8)]"></span>
                <p className="text-xs font-bold uppercase tracking-[0.15em] text-slate-300">Top Matches</p>
              </div>
              <h1 className="font-display text-4xl font-bold tracking-tight sm:text-5xl text-white">Candidates for {vereq}</h1>
              <p className="text-base text-slate-400">Review the top 30 candidates matched for this requisition.</p>
            </div>

            {/* Bulk Actions Header Controls */}
            <div className="flex flex-wrap items-center gap-3">
              {selectedIds.length > 0 && (
                <span className="text-xs font-semibold text-slate-300 bg-slate-800/80 px-3.5 py-2.5 rounded-xl border border-slate-700 shadow-sm">
                  <span className="text-green-400 font-bold">{selectedIds.length}</span> of {eligibleCandidates.length} selected
                </span>
              )}
              <button
                onClick={() => setBulkModalOpen(true)}
                disabled={loading || selectedIds.length === 0}
                className="inline-flex items-center gap-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-green-600 px-5 py-3 text-sm font-bold text-white shadow-[0_0_20px_rgba(34,197,94,0.35)] hover:from-emerald-500 hover:to-green-500 hover:-translate-y-0.5 active:translate-y-0 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0 cursor-pointer"
              >
                <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12.031 6.172c-3.181 0-5.767 2.586-5.768 5.766-.001 1.298.38 2.27 1.019 3.287l-.582 2.128 2.182-.573c.978.58 1.711.892 2.81.892 3.181 0 5.767-2.585 5.767-5.766 0-3.18-2.585-5.766-5.767-5.766zm3.333 8.273c-.156.444-.946.853-1.309.897-.323.039-.773.08-2.147-.487-1.666-.688-2.73-2.404-2.81-2.511-.08-.107-.673-.897-.673-1.714 0-.817.427-1.218.578-1.378.151-.16.329-.2.445-.2.116 0 .231 0 .329.004.098.004.227-.04.356.262.133.311.453 1.102.493 1.182.04.08.067.173.013.28-.053.107-.08.173-.16.258-.08.084-.169.191-.235.258-.08.08-.165.17-.067.338.098.169.435.718.934 1.164.646.577 1.182.756 1.343.836.16.08.254.067.347-.04.093-.107.404-.471.516-.631.111-.16.222-.133.364-.08.142.053.898.423 1.054.503.156.08.262.115.302.182.04.067.04.387-.116.831z"/>
                </svg>
                Send Bulk Invites ({selectedIds.length})
              </button>
            </div>
          </div>

          <div className="glass-dark rounded-[24px] overflow-hidden animate-slide-up opacity-0-init animate-delay-300 border border-slate-800/50">
            <div className="overflow-auto max-h-[600px] custom-scrollbar pb-2 pr-1 relative">
              <table className="w-full min-w-[960px] text-left border-collapse">
                <thead className="sticky top-0 bg-[#0B1121] z-10 before:absolute before:inset-0 before:bg-slate-900/50 before:-z-10 before:backdrop-blur-md">
                  <tr className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    <th className="py-4 pl-6 border-b border-slate-700 w-12 text-center">
                      <input
                        type="checkbox"
                        checked={isAllSelected}
                        onChange={handleToggleSelectAll}
                        disabled={loading || eligibleCandidates.length === 0}
                        title={isAllSelected ? "Deselect all" : "Select all eligible candidates"}
                        className="size-4 rounded border-slate-600 bg-slate-800 text-green-500 focus:ring-green-500 focus:ring-offset-slate-900 cursor-pointer disabled:opacity-30"
                      />
                    </th>
                    <th className="py-4 pl-3 border-b border-slate-700">Candidate</th>
                    <th className="py-4 border-b border-slate-700">Email / Phone</th>
                    <th className="py-4 border-b border-slate-700">Classification</th>
                    <th className="py-4 border-b border-slate-700">Score</th>
                    <th className="py-4 pr-6 text-right border-b border-slate-700">Action / Resume</th>
                  </tr>
                </thead>
                <tbody className="text-sm">
                  {loading ? (
                    <tr><td colSpan="6" className="py-12 text-center">
                      <div className="inline-flex flex-col items-center gap-3 text-slate-400">
                        <svg className="w-8 h-8 animate-spin text-accent" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeDasharray="30 60" className="opacity-75"></circle>
                        </svg>
                        <span>{statusText}</span>
                      </div>
                    </td></tr>
                  ) : error ? (
                    <tr><td colSpan="6" className="py-12 text-center text-red-400">
                      Error: {error}
                    </td></tr>
                  ) : candidates.length === 0 ? (
                    <tr><td colSpan="6" className="py-12 text-center text-slate-500">
                      No candidates found for this requisition.
                    </td></tr>
                  ) : (
                    candidates.slice(0, 30).map((c, index) => {
                      const cId = c.candidate_id || c.id;
                      const isInvited = isCandidateInvited(c);
                      const hasPhone = hasCandidatePhone(c);
                      const isChecked = selectedIds.includes(cId);

                      return (
                        <tr key={cId || index} className="table-row-hover border-b border-slate-800/50 group">
                          <td className="py-5 pl-6 text-center">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => handleToggleSelect(cId)}
                              disabled={isInvited || !hasPhone}
                              title={isInvited ? "Already invited" : !hasPhone ? "No phone number available" : "Select candidate"}
                              className="size-4 rounded border-slate-600 bg-slate-800 text-green-500 focus:ring-green-500 focus:ring-offset-slate-900 cursor-pointer disabled:opacity-25 disabled:cursor-not-allowed"
                            />
                          </td>
                          <td className="py-5 pl-3">
                            <p className="font-bold text-white text-base">{c.name || 'Unknown Name'}</p>
                          </td>
                          <td className="py-5">
                            {c.email && <p className="font-medium text-slate-300">{c.email}</p>}
                            {c.phone && <p className="text-[11px] text-slate-500 font-mono">{c.phone}</p>}
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
                                disabled={isInvited || !hasPhone}
                                className={`inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-bold transition-colors cursor-pointer ${
                                  isInvited
                                    ? 'bg-green-500/20 text-green-500 border border-green-500/30'
                                    : !hasPhone
                                    ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                                    : 'bg-green-600 text-white hover:bg-green-500 shadow-sm'
                                }`}
                              >
                                {isInvited ? "✓ Invited" : !hasPhone ? "No Phone" : "WhatsApp"}
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
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
