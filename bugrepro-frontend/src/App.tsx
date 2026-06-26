import React, { useState, useEffect, useRef } from 'react';
import {
  Shield,
  Sun,
  Moon,
  Play,
  Terminal,
  CheckCircle,
  XCircle,
  Loader2,
  FileText,
  AlertCircle,
  StopCircle,
  RotateCcw
} from 'lucide-react';
import {
  RingLoader,
  SyncLoader,
  HashLoader,
  CircleLoader,
  BounceLoader
} from 'react-spinners';

interface LogLine {
  id: string;
  timestamp: string;
  author: string;
  text: string;
  type: 'info' | 'success' | 'error' | 'warning' | 'agent' | 'system';
}

interface Phase {
  name: string;
  description: string;
  status: 'pending' | 'active' | 'completed' | 'failed';
}

interface IssueDetails {
  title: string;
  body: string;
  repoName: string;
  number: string;
}

const stripMarkdown = (md: string): string => {
  if (!md) return '';
  return md
    .replace(/```[\s\S]*?```/g, '') // remove code blocks
    .replace(/#+\s+.+/g, '') // remove headings
    .replace(/`([^`]+)`/g, '$1') // remove inline code
    .replace(/\*\*([^*]+)\*\*/g, '$1') // remove bold
    .replace(/\*([^*]+)\*/g, '$1') // remove italic
    .replace(/^\s*[-*+]\s+/gm, '') // remove bullet points
    .replace(/\n+/g, ' ') // collapse whitespace
    .replace(/\s+/g, ' ')
    .trim();
};

export default function App() {
  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
  const [issueUrl, setIssueUrl] = useState('');
  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'failed' | 'stopped'>('idle');
  const [theme, setTheme] = useState<'dark' | 'light'>('light');
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [report, setReport] = useState<string>('');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [issueDetails, setIssueDetails] = useState<IssueDetails | null>(null);
  const [isDescExpanded, setIsDescExpanded] = useState(false);
  const [isTerminalMaximized, setIsTerminalMaximized] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isResettingRef = useRef(false);

  const resetWorkspace = () => {
    isResettingRef.current = true;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStatus('idle');
    setIssueUrl('');
    setIssueDetails(null);
    setIsDescExpanded(false);
    setIsTerminalMaximized(false);
    setLogs([]);
    setReport('');
    setErrorMsg('');
    setPhases([
      { name: 'Issue Triage', description: 'Checking issue details and eligibility.', status: 'pending' },
      { name: 'Sandbox Setup', description: 'Cloning repo & installing dependencies in Docker.', status: 'pending' },
      { name: 'Bug Reproduction', description: 'Creating and running a reproduction test.', status: 'pending' },
      { name: 'Patch Proposal', description: 'Generating and applying a minimal code fix.', status: 'pending' },
      { name: 'Verification', description: 'Re-running tests and extracting git diff.', status: 'pending' }
    ]);
  };

  // Phase checklist
  const [phases, setPhases] = useState<Phase[]>([
    { name: 'Issue Triage', description: 'Checking issue details and eligibility.', status: 'pending' },
    { name: 'Sandbox Setup', description: 'Cloning repo & installing dependencies in Docker.', status: 'pending' },
    { name: 'Bug Reproduction', description: 'Creating and running a reproduction test.', status: 'pending' },
    { name: 'Patch Proposal', description: 'Generating and applying a minimal code fix.', status: 'pending' },
    { name: 'Verification', description: 'Re-running tests and extracting git diff.', status: 'pending' }
  ]);

  const terminalEndRef = useRef<HTMLDivElement>(null);

  // Initialize theme on mount
  useEffect(() => {
    const body = document.body;
    if (theme === 'dark') {
      body.classList.add('dark-theme');
    } else {
      body.classList.remove('dark-theme');
    }
  }, [theme]);

  // Scroll to bottom of terminal when logs update
  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  const addLog = (author: string, text: string, type: LogLine['type'] = 'info') => {
    setLogs(prev => {
      // Append text if the last log line has the same author and type (agent streaming)
      if (prev.length > 0 && prev[prev.length - 1].author === author && prev[prev.length - 1].type === type) {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          text: updated[updated.length - 1].text + text
        };
        return updated;
      } else {
        const timestamp = new Date().toLocaleTimeString();
        const id = Math.random().toString(36).substring(7);
        return [...prev, { id, timestamp, author, text, type }];
      }
    });
  };

  const lastAuthorRef = useRef<string>('');
  const streamedInvocationsRef = useRef<Set<string>>(new Set());

  const updatePhase = (name: string, status: Phase['status']) => {
    setPhases(prev => prev.map(p => p.name === name ? { ...p, status } : p));
  };

  const handleSSEEvent = (event: any) => {
    const author = event.author || 'system';

    // Do not double-print content parts from INVOCATION_COMPLETED or final response events
    // since their content has already been streamed chunk-by-chunk in real-time.
    const isCompleted = event.type === 'INVOCATION_COMPLETED' || event.final_response === true;

    const invocationId = event.invocationId || event.invocation_id || event.id;
    const isPartial = event.partial === true;
    const hasAlreadyStreamed = invocationId ? streamedInvocationsRef.current.has(invocationId) : false;

    if (isPartial && invocationId) {
      streamedInvocationsRef.current.add(invocationId);
    }

    const shouldSkipContent = hasAlreadyStreamed && !isPartial;

    // Check if the event has printable model text content
    if (event.content && event.content.parts && !isCompleted && !shouldSkipContent) {
      for (const part of event.content.parts) {
        if (part.text) {
          const textChunk = part.text;

          // Stream verification agent output directly to the report panel
          if (author === 'verification_agent') {
            if (lastAuthorRef.current !== author) {
              lastAuthorRef.current = author;
              setReport(textChunk);
            } else {
              setReport(prev => prev + textChunk);
            }
          }

          // Add to log terminal
          addLog(author, textChunk, 'agent');
        }
      }
    }

    // Determine current phase based on agent lifecycle logs
    if (author === 'issue_triage_agent') {
      updatePhase('Issue Triage', 'active');
    } else if (author === 'repo_setup_agent') {
      updatePhase('Issue Triage', 'completed');
      updatePhase('Sandbox Setup', 'active');
    } else if (author === 'reproduction_agent') {
      updatePhase('Sandbox Setup', 'completed');
      updatePhase('Bug Reproduction', 'active');
    } else if (author === 'patch_agent') {
      updatePhase('Bug Reproduction', 'completed');
      updatePhase('Patch Proposal', 'active');
    } else if (author === 'verification_agent') {
      updatePhase('Patch Proposal', 'completed');
      updatePhase('Verification', 'active');
    }
  };

  const stopExecution = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  const startSentinel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!issueUrl.trim()) return;

    // Security Policy Validation: Ensure it's a valid GitHub Issue URL
    const match = issueUrl.match(/github\.com\/([^/]+)\/([^/]+)\/issues\/(\d+)/);
    if (!match) {
      setErrorMsg('Security Policy Violation: Invalid URL. Sentinel only accepts valid public GitHub issue URLs (e.g., https://github.com/owner/repo/issues/123).');
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setStatus('running');
    setLogs([]);
    setReport('');
    lastAuthorRef.current = '';
    streamedInvocationsRef.current.clear();
    setErrorMsg('');
    setPhases([
      { name: 'Issue Triage', description: 'Checking issue details and eligibility.', status: 'pending' },
      { name: 'Sandbox Setup', description: 'Cloning repo & installing dependencies in Docker.', status: 'pending' },
      { name: 'Bug Reproduction', description: 'Creating and running a reproduction test.', status: 'pending' },
      { name: 'Patch Proposal', description: 'Generating and applying a minimal code fix.', status: 'pending' },
      { name: 'Verification', description: 'Re-running tests and extracting git diff.', status: 'pending' }
    ]);

    // Parse GitHub Issue URL and fetch details
    const urlMatch = issueUrl.match(/github\.com\/([^/]+)\/([^/]+)\/issues\/(\d+)/)!;
    const owner = urlMatch[1];
    const repo = urlMatch[2];
    const number = urlMatch[3];

    const userId = `web_user_${Math.floor(Math.random() * 1000)}`;

    try {
      addLog('System', 'Validating GitHub issue eligibility...', 'system');
      setIssueDetails({
        title: 'Validating issue details...',
        body: '',
        repoName: `${owner}/${repo}`,
        number: number
      });

      let issueData = null;
      try {
        const ghRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/issues/${number}`, { signal: controller.signal });
        if (ghRes.ok) {
          issueData = await ghRes.json();
        } else if (ghRes.status === 404) {
          throw new Error('The specified GitHub issue could not be found. Please check that the URL is correct and the repository is public.');
        } else if (ghRes.status !== 403) {
          throw new Error(`Failed to validate GitHub issue: HTTP ${ghRes.status}`);
        }
      } catch (ghErr: any) {
        if (ghErr.name === 'AbortError') throw ghErr;
        if (ghErr.message.includes('could not be found') || ghErr.message.includes('Failed to validate')) {
          throw ghErr;
        }
        console.warn('GitHub API pre-validation warning (bypassing):', ghErr);
      }

      if (issueData) {
        setIssueDetails({
          title: issueData.title || 'Untitled Issue',
          body: issueData.body || 'No description provided.',
          repoName: `${owner}/${repo}`,
          number: number
        });
      } else {
        setIssueDetails({
          title: `Issue #${number}`,
          body: `View issue details on GitHub: ${issueUrl}`,
          repoName: `${owner}/${repo}`,
          number: number
        });
      }

      addLog('System', 'Starting session...', 'system');

      // 1. Create session via FastAPI session service
      const sessionRes = await fetch(`${API_BASE_URL}/apps/app/users/${userId}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: {} }),
        signal: controller.signal
      });

      if (!sessionRes.ok) {
        throw new Error(`Failed to initialize session: ${sessionRes.statusText}`);
      }

      const sessionData = await sessionRes.json();
      const sessionId = sessionData.id;
      addLog('System', `Session established successfully (ID: ${sessionId.slice(0, 8)}...)`, 'success');

      // 2. Open ReadableStream connection to read the POST SSE stream
      addLog('System', 'Triggering Sentinel multi-agent workflow...', 'system');
      const response = await fetch(`${API_BASE_URL}/run_sse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_name: 'app',
          user_id: userId,
          session_id: sessionId,
          new_message: {
            role: 'user',
            parts: [{ text: issueUrl }]
          },
          streaming: true
        }),
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error(`Execution error: Server returned ${response.status} (${response.statusText})`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error('Response body is not readable');

      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6);
            try {
              const eventData = JSON.parse(jsonStr);
              handleSSEEvent(eventData);

              // End condition detection based on finished invocation event
              if (eventData.type === 'INVOCATION_COMPLETED' || eventData.final_response === true) {
                addLog('System', 'Sentinel workflow completed successfully.', 'success');
              }
            } catch (err) {
              console.error('Failed to parse SSE event:', err);
            }
          }
        }
      }

      setStatus('completed');
      updatePhase('Verification', 'completed');
    } catch (err: any) {
      if (err.name === 'AbortError') {
        if (isResettingRef.current) {
          isResettingRef.current = false;
          return;
        }
        setStatus('stopped');
        addLog('System', 'Sentinel Agent execution stopped by user.', 'warning');
        setPhases(prev => prev.map(p => p.status === 'active' || p.status === 'pending' ? { ...p, status: 'failed' } : p));
        return;
      }
      console.error(err);
      setErrorMsg(err.message || 'An unexpected error occurred during execution.');
      setStatus('failed');
      addLog('System', `Error: ${err.message}`, 'error');
      // Mark current active phase as failed
      setPhases(prev => prev.map(p => p.status === 'active' ? { ...p, status: 'failed' } : p));
    } finally {
      isResettingRef.current = false;
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  };

  const renderPhaseSpinner = (phaseName: string) => {
    switch (phaseName) {
      case 'Issue Triage':
        return <RingLoader color="#a855f7" size={60} speedMultiplier={1} />;
      case 'Sandbox Setup':
        return <SyncLoader color="#f97316" size={12} speedMultiplier={1} margin={4} />;
      case 'Bug Reproduction':
        return <HashLoader color="#f43f5e" size={50} speedMultiplier={1} />;
      case 'Patch Proposal':
        return <CircleLoader color="#14b8a6" size={55} speedMultiplier={1} />;
      case 'Verification':
        return <BounceLoader color="#3b82f6" size={55} speedMultiplier={1} />;
      default:
        return <Loader2 className="animate-spin" size={48} style={{ color: 'hsl(var(--primary))' }} />;
    }
  };

  // Premium inline Markdown parser to render structured report & highlighted git diffs
  const renderMarkdown = (md: string) => {
    if (!md) return null;

    const formatInline = (text: string): React.ReactNode[] => {
      // Use lookahead (?!\s) and lookbehind (?<!\s) for bold/italic to prevent literal asterisk collisions
      const parts = text.split(/(\*\*(?!\s).+?(?<!\s)\*\*|\*(?!\s).+?(?<!\s)\*|`[^`]+?`)/g);
      return parts.map((part, index) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return <strong key={index}>{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith('*') && part.endsWith('*')) {
          return <em key={index}>{part.slice(1, -1)}</em>;
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return <code key={index} style={{
            fontFamily: 'var(--font-mono)',
            backgroundColor: 'rgba(128, 128, 128, 0.15)',
            padding: '2px 4px',
            borderRadius: '4px',
            fontSize: '0.9em'
          }}>{part.slice(1, -1)}</code>;
        }
        return part;
      });
    };

    const lines = md.split('\n');
    const elements: React.ReactNode[] = [];
    let currentCodeBlock: { lang: string; lines: string[]; leadingSpacesCount: number } | null = null;
    let currentList: { type: 'ul' | 'ol'; items: string[] } | null = null;
    let currentBlockquote: { type: string; lines: string[] } | null = null;

    const flushList = (key: number) => {
      if (currentList) {
        if (currentList.type === 'ol') {
          elements.push(
            <ol key={`list-${key}`} style={{ paddingLeft: '24px', listStyleType: 'decimal', margin: '8px 0' }}>
              {currentList.items.map((item, idx) => (
                <li key={idx} style={{ marginBottom: '4px' }}>{formatInline(item)}</li>
              ))}
            </ol>
          );
        } else {
          elements.push(
            <ul key={`list-${key}`} style={{ paddingLeft: '24px', listStyleType: 'disc', margin: '8px 0' }}>
              {currentList.items.map((item, idx) => (
                <li key={idx} style={{ marginBottom: '4px' }}>{formatInline(item)}</li>
              ))}
            </ul>
          );
        }
        currentList = null;
      }
    };

    const flushBlockquote = (key: number) => {
      if (currentBlockquote) {
        let alertClass = 'alert-note';
        if (currentBlockquote.type.includes('IMPORTANT') || currentBlockquote.type.includes('WARNING') || currentBlockquote.type.includes('CAUTION')) {
          alertClass = 'alert-warning';
        } else if (currentBlockquote.type.includes('TIP') || currentBlockquote.type.includes('SUCCESS')) {
          alertClass = 'alert-tip';
        }
        elements.push(
          <blockquote key={`quote-${key}`} className={`report-blockquote ${alertClass}`} style={{
            padding: '12px 16px',
            borderLeft: '4px solid',
            borderRadius: '0 8px 8px 0',
            margin: '12px 0',
            backgroundColor: alertClass === 'alert-warning' ? 'rgba(245, 158, 11, 0.08)' : 'rgba(37, 99, 235, 0.08)'
          }}>
            {currentBlockquote.lines.map((line, idx) => (
              <p key={idx} style={{ margin: 0 }}>{formatInline(line)}</p>
            ))}
          </blockquote>
        );
        currentBlockquote = null;
      }
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      // Code blocks handler
      if (trimmed.startsWith('```')) {
        if (currentCodeBlock) {
          const isDiff = currentCodeBlock.lang === 'diff' ||
            currentCodeBlock.lines.some(l => {
              const t = l.trim();
              return t.startsWith('diff --git') || t.startsWith('--- ') || t.startsWith('+++ ');
            });
          elements.push(
            <div key={`code-${i}`} className="diff-container">
              <div className="diff-header">{isDiff ? 'DIFF' : currentCodeBlock.lang.toUpperCase()} VIEW</div>
              <div className="diff-body" style={{ padding: '12px 16px', overflowX: 'auto', backgroundColor: '#0b0f19' }}>
                {currentCodeBlock.lines.map((codeLine, idx) => {
                  let lineClass = '';
                  if (isDiff) {
                    const trimmedLine = codeLine.trim();
                    if (trimmedLine.startsWith('+') && !trimmedLine.startsWith('+++')) lineClass = 'addition';
                    else if (trimmedLine.startsWith('-') && !trimmedLine.startsWith('---')) lineClass = 'deletion';
                    else if (trimmedLine.startsWith('@@') || trimmedLine.startsWith('diff') || trimmedLine.startsWith('index ')) lineClass = 'header';
                  }
                  return (
                    <span key={idx} className={`diff-line ${lineClass}`} style={{
                      display: 'block',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.82rem',
                      lineHeight: '1.5',
                      color: lineClass === 'addition' ? '#34d399' : lineClass === 'deletion' ? '#f87171' : lineClass === 'header' ? '#818cf8' : '#e2e8f0',
                      backgroundColor: lineClass === 'addition' ? 'rgba(52, 211, 153, 0.1)' : lineClass === 'deletion' ? 'rgba(248, 113, 113, 0.1)' : 'transparent'
                    }}>
                      {codeLine}
                    </span>
                  );
                })}
              </div>
            </div>
          );
          currentCodeBlock = null;
        } else {
          flushList(i);
          flushBlockquote(i);
          const lang = trimmed.slice(3).trim().toLowerCase() || 'text';
          const matchSpaces = line.match(/^(\s*)/);
          const leadingSpacesCount = matchSpaces ? matchSpaces[1].length : 0;
          currentCodeBlock = { lang, lines: [], leadingSpacesCount };
        }
        continue;
      }

      if (currentCodeBlock) {
        let codeLine = line;
        if (currentCodeBlock.leadingSpacesCount > 0) {
          const matchSpaces = line.match(/^(\s*)/);
          const currentSpaces = matchSpaces ? matchSpaces[1].length : 0;
          const stripCount = Math.min(currentCodeBlock.leadingSpacesCount, currentSpaces);
          codeLine = line.slice(stripCount);
        }
        currentCodeBlock.lines.push(codeLine);
        continue;
      }

      // Blockquotes/Alerts handler
      if (trimmed.startsWith('>')) {
        flushList(i);
        const index = line.indexOf('>');
        const content = line.slice(index + 1).trim();
        if (!currentBlockquote) {
          let type = 'note';
          if (content.startsWith('[!')) {
            type = content;
          }
          currentBlockquote = { type, lines: content.startsWith('[!') ? [] : [content] };
        } else {
          currentBlockquote.lines.push(content);
        }
        continue;
      } else {
        flushBlockquote(i);
      }

      // Lists handler
      const isUnorderedList = trimmed.startsWith('- ') || trimmed.startsWith('* ');
      const isOrderedList = /^\d+\.\s+/.test(trimmed);
      if (isUnorderedList || isOrderedList) {
        let content = '';
        const listType = isOrderedList ? 'ol' : 'ul';

        if (isUnorderedList) {
          content = trimmed.slice(2).trim();
        } else {
          const match = trimmed.match(/^\d+\.\s+/);
          if (match) {
            content = trimmed.slice(match[0].length).trim();
          }
        }

        if (!currentList) {
          currentList = { type: listType, items: [content] };
        } else if (currentList.type !== listType) {
          flushList(i);
          currentList = { type: listType, items: [content] };
        } else {
          currentList.items.push(content);
        }
        continue;
      } else {
        flushList(i);
      }

      // Headings handler
      if (trimmed.startsWith('# ')) {
        elements.push(<h2 key={i} style={{ fontSize: '1.6rem', marginTop: '24px', borderBottom: '1px solid hsl(var(--border))', paddingBottom: '6px' }}>{formatInline(trimmed.slice(2))}</h2>);
      } else if (trimmed.startsWith('## ')) {
        elements.push(<h3 key={i} style={{ fontSize: '1.25rem', marginTop: '16px' }}>{formatInline(trimmed.slice(3))}</h3>);
      } else if (trimmed.startsWith('### ')) {
        elements.push(<h4 key={i} style={{ fontSize: '1.05rem', marginTop: '12px' }}>{formatInline(trimmed.slice(4))}</h4>);
      } else if (trimmed) {
        elements.push(<p key={i} style={{ margin: '8px 0', fontSize: '0.95rem' }}>{formatInline(trimmed)}</p>);
      }
    }

    flushList(lines.length);
    flushBlockquote(lines.length);

    return <div className="report-markdown">{elements}</div>;
  };

  const activePhase = phases.find(p => p.status === 'active') || phases.find(p => p.status === 'pending');

  return (
    <div className="app-container">
      {/* Premium Header */}
      <header className="app-header">
        <div className="header-logo">
          <span className="logo-icon">🛡️</span>
          <div className="logo-text">
            <h1>BugRepro Sentinel</h1>
            <div className="logo-subtitle">Secure Autonomous Bug Repair</div>
          </div>
        </div>
        <div className="header-controls">
          <button onClick={toggleTheme} className="icon-btn" title="Toggle Light/Dark Theme">
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </header>

      {/* Main Workspace Workspace */}
      <div className="workspace-grid">
        {/* Left Pane - Execution Controls / Real-time Logs */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">
              <Terminal size={18} />
              Execution Workspace
            </span>
            {status === 'running' && (
              <span className="status-badge running">
                <Loader2 size={14} className="animate-spin" />
                Sentinel Active
              </span>
            )}
            {status === 'completed' && (
              <span className="status-badge passed">
                <CheckCircle size={14} />
                Execution Passed
              </span>
            )}
            {status === 'failed' && (
              <span className="status-badge failed">
                <XCircle size={14} />
                Execution Failed
              </span>
            )}
            {status === 'stopped' && (
              <span className="status-badge stopped">
                <XCircle size={14} />
                Execution Stopped
              </span>
            )}
          </div>

          <div className="panel-body">
            {status === 'idle' ? (
              <div className="input-form-wrapper">
                <div style={{ textAlign: 'center', marginBottom: '16px' }}>
                  <Shield size={64} style={{ color: 'hsl(var(--primary))', opacity: 0.85, marginBottom: '12px' }} />
                  <h2 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Sandbox Repair Engine</h2>
                  <p style={{ color: 'hsl(var(--muted))', fontSize: '0.9rem', marginTop: '6px' }}>
                    Enter a public Python repository issue URL to automatically isolate, reproduce, patch, and verify the fix.
                  </p>
                </div>
                {errorMsg && (
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    backgroundColor: 'hsl(var(--error-bg))',
                    color: 'hsl(var(--error))',
                    padding: '12px 16px',
                    borderRadius: '8px',
                    marginBottom: '16px',
                    fontSize: '0.9rem',
                    border: '1px solid rgba(239, 68, 68, 0.2)'
                  }}>
                    <AlertCircle size={16} />
                    <span>{errorMsg}</span>
                  </div>
                )}
                <form onSubmit={startSentinel} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div className="input-group">
                    <label htmlFor="issue-url">GitHub Issue URL</label>
                    <input
                      id="issue-url"
                      type="url"
                      value={issueUrl}
                      onChange={(e) => setIssueUrl(e.target.value)}
                      placeholder="https://github.com/owner/repo/issues/123"
                      required
                      className="text-input"
                    />
                  </div>
                  <button type="submit" className="btn">
                    <Play size={16} />
                    Launch Sentinel Agent
                  </button>
                </form>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '20px' }}>
                {!isTerminalMaximized && issueDetails && (
                  <div className="active-issue-card">
                    <div className="issue-meta">
                      <span className="repo-badge">{issueDetails.repoName}</span>
                      {issueDetails.number && (
                        <span className="issue-number">#{issueDetails.number}</span>
                      )}
                    </div>
                    <h3 className="issue-title">{issueDetails.title}</h3>
                    {issueDetails.body && (
                      <div className="issue-desc-container">
                        {isDescExpanded ? (
                          <div className="issue-desc expanded">
                            {renderMarkdown(issueDetails.body)}
                          </div>
                        ) : (
                          <p className="issue-desc collapsed">
                            {stripMarkdown(issueDetails.body)}
                          </p>
                        )}
                        {issueDetails.body.length > 180 && (
                          <button
                            type="button"
                            className="btn-link"
                            onClick={() => setIsDescExpanded(!isDescExpanded)}
                            style={{
                              background: 'none',
                              border: 'none',
                              color: 'hsl(var(--primary))',
                              fontSize: '0.8rem',
                              fontWeight: 600,
                              padding: 0,
                              cursor: 'pointer',
                              marginTop: '6px',
                              textAlign: 'left'
                            }}
                          >
                            {isDescExpanded ? 'Show Less' : 'Show More'}
                          </button>
                        )}
                      </div>
                    )}
                    <div className="issue-actions">
                      <button
                        type="button"
                        disabled={status !== 'running'}
                        onClick={stopExecution}
                        className="btn btn-stop"
                      >
                        <StopCircle size={16} />
                        Stop Agent Run
                      </button>
                      <button
                        type="button"
                        onClick={resetWorkspace}
                        className="btn btn-another"
                      >
                        <RotateCcw size={16} />
                        Reset and Run another
                      </button>
                    </div>
                  </div>
                )}

                {/* Real-time Phases checklist */}
                {!isTerminalMaximized && (
                  <div className="phases-timeline">
                    {phases.map((p, idx) => (
                      <div key={idx} className={`phase-item ${p.status}`}>
                        <div className="phase-status-icon">
                          {p.status === 'pending' && <span style={{ fontSize: '0.8rem', fontWeight: 'bold' }}>{idx + 1}</span>}
                          {p.status === 'active' && <Loader2 size={14} className="animate-spin" />}
                          {p.status === 'completed' && <CheckCircle size={14} />}
                          {p.status === 'failed' && <XCircle size={14} />}
                        </div>
                        <div className="phase-info">
                          <div className="phase-name">{p.name}</div>
                          <div className="phase-desc">{p.description}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Live Sandbox Terminal console logs */}
                <div style={{ flex: 1, minHeight: isTerminalMaximized ? '100%' : '200px', display: 'flex', flexDirection: 'column' }}>
                  <div className="terminal-wrapper" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                    <div className="terminal-header">
                      <div className="terminal-dots">
                        <div className="terminal-dot red"></div>
                        <div className="terminal-dot yellow"></div>
                        <div className="terminal-dot green"></div>
                      </div>
                      <span className="terminal-title">sandbox@sentinel:~/workspace</span>
                      <button
                        type="button"
                        onClick={() => setIsTerminalMaximized(!isTerminalMaximized)}
                        className="terminal-btn-maximize"
                        title={isTerminalMaximized ? "Restore Terminal" : "Maximize Terminal"}
                        style={{
                          background: 'rgba(255, 255, 255, 0.1)',
                          border: 'none',
                          borderRadius: '4px',
                          color: '#e2e8f0',
                          fontSize: '0.72rem',
                          fontWeight: 600,
                          padding: '2px 8px',
                          cursor: 'pointer',
                          transition: 'background 0.2s',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px'
                        }}
                      >
                        {isTerminalMaximized ? "Restore" : "Maximize"}
                      </button>
                    </div>
                    <div className="terminal-body" style={{ flex: 1 }}>
                      {logs.map((log) => (
                        <div key={log.id} className={`terminal-line ${log.type}`}>
                          <span style={{ opacity: 0.5, marginRight: '8px' }}>[{log.timestamp}]</span>
                          <span style={{ color: 'hsl(var(--primary))', fontWeight: 600, marginRight: '4px' }}>
                            {log.author}:
                          </span>
                          {log.text}
                        </div>
                      ))}
                      {status === 'running' && (
                        <div className="terminal-line">
                          <span style={{ opacity: 0.5, marginRight: '8px' }}>[{new Date().toLocaleTimeString()}]</span>
                          <span style={{ color: 'hsl(var(--primary))', fontWeight: 600 }}>agent:</span>
                          <span className="cursor"></span>
                        </div>
                      )}
                      <div ref={terminalEndRef}></div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Pane - Evidence Report & Git Diffs */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">
              <FileText size={18} />
              Sentinel Evidence Report
            </span>
          </div>

          <div className="panel-body">
            {report ? (
              <div style={{ padding: '8px' }}>
                {renderMarkdown(report)}
              </div>
            ) : (
              <div className="report-empty-state">
                {status === 'running' ? (
                  <div key={activePhase ? activePhase.name : 'empty'} className="animate-fade-in-up" style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '24px'
                  }}>
                    <div className="custom-spinner-wrapper" style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      height: '80px',
                      minHeight: '80px',
                    }}>
                      {renderPhaseSpinner(activePhase ? activePhase.name : '')}
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <h3 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'hsl(var(--primary))' }}>
                        {activePhase ? activePhase.name : 'Analyzing Repository...'}
                      </h3>
                      <p style={{ fontSize: '0.875rem', marginTop: '6px', color: 'hsl(var(--muted))' }}>
                        {activePhase ? activePhase.description : 'The agents are setting up the Docker sandbox and reproducing the issue. The report will update here as components are verified.'}
                      </p>
                    </div>
                  </div>
                ) : (
                  <>
                    <span className="report-empty-icon">🛡️</span>
                    <div>
                      <h3 style={{ fontSize: '1.25rem', fontWeight: 600 }}>No Report Generated</h3>
                      <p style={{ fontSize: '0.875rem', marginTop: '6px' }}>
                        Launch the Sentinel Agent on the left panel to begin. The final verified patch details and unified git diff will display here.
                      </p>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
