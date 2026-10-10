import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  Database,
  Lock,
  MessageSquare,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const FEATURES = [
  {
    icon: Sparkles,
    title: 'AI-generated SQL',
    body: 'A real language model turns plain-English questions into PostgreSQL queries built from your live schema.',
  },
  {
    icon: ShieldCheck,
    title: 'Independent validation',
    body: 'Every generated statement is parsed and checked by application code before it can run — read-only, always.',
  },
  {
    icon: Database,
    title: 'Your actual database',
    body: 'Connect any authorized PostgreSQL database, inspect its real schema, and query the real records.',
  },
  {
    icon: BarChart3,
    title: 'Instant visualization',
    body: 'Results render as tables and charts with execution metadata, and export cleanly to CSV.',
  },
  {
    icon: MessageSquare,
    title: 'Conversational follow-ups',
    body: 'Refine answers with context: "only for 2026", "sort from highest to lowest" — each turn generates fresh SQL.',
  },
  {
    icon: Lock,
    title: 'Protected by design',
    body: 'Encrypted credentials, session cookies, CSRF protection, ownership checks and per-user rate limits.',
  },
];

const STEPS = [
  { step: '01', title: 'Ask', body: 'Type a question in plain English and pick a connection.' },
  { step: '02', title: 'Review', body: 'Inspect the generated SQL and its security validation report.' },
  { step: '03', title: 'Execute', body: 'Approve execution and read actual rows from your database.' },
  { step: '04', title: 'Explore', body: 'Visualize, export, save and revisit every query.' },
];

export default function Landing() {
  const { user } = useAuth();

  return (
    <div className="min-h-screen bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      {/* Navigation */}
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
          <div className="flex items-center gap-2 font-semibold">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
              <Sparkles className="h-4 w-4" />
            </span>
            QueryMind AI
          </div>
          <nav className="flex items-center gap-4 text-sm">
            <a href="#features" className="hidden text-slate-600 hover:text-brand-600 dark:text-slate-300 sm:inline">
              Features
            </a>
            <a href="#how" className="hidden text-slate-600 hover:text-brand-600 dark:text-slate-300 sm:inline">
              How it works
            </a>
            <a href="#security" className="hidden text-slate-600 hover:text-brand-600 dark:text-slate-300 sm:inline">
              Security
            </a>
            {user ? (
              <Link to="/app" className="btn-primary">
                Open dashboard
              </Link>
            ) : (
              <>
                <Link to="/login" className="btn-secondary">
                  Sign in
                </Link>
                <Link to="/register" className="btn-primary">
                  Get started
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-4 pb-20 pt-16 text-center sm:pt-24">
        <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 dark:border-brand-800 dark:bg-brand-950 dark:text-brand-300">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
          Read-only by design · Your data never leaves your database
        </span>
        <h1 className="mx-auto max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl">
          Your Data. Your Questions. Instant{' '}
          <span className="text-brand-600 dark:text-brand-400">SQL Intelligence.</span>
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600 dark:text-slate-400">
          Ask questions in plain English, generate SQL using AI, and discover insights directly from
          your database.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link to="/register" className="btn-primary px-6 py-3 text-base">
            Start querying <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
          <Link to="/login" className="btn-secondary px-6 py-3 text-base">
            Sign in
          </Link>
        </div>
        <div className="mx-auto mt-12 max-w-3xl rounded-xl border border-slate-200 bg-slate-50 p-4 text-left dark:border-slate-800 dark:bg-slate-900">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Example question
          </p>
          <p className="mt-2 font-mono text-sm text-slate-700 dark:text-slate-300">
            “Which products had the highest revenue last quarter, and how did that compare with the
            quarter before?”
          </p>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="border-t border-slate-200 bg-slate-50 py-16 dark:border-slate-800 dark:bg-slate-900/40">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-center text-2xl font-bold sm:text-3xl">Built for real analytics work</h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="card p-5">
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-brand-100 text-brand-700 dark:bg-brand-900/50 dark:text-brand-300">
                  <f.icon className="h-5 w-5" aria-hidden />
                </div>
                <h3 className="font-semibold">{f.title}</h3>
                <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-400">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="py-16">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-center text-2xl font-bold sm:text-3xl">How it works</h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s) => (
              <div key={s.step} className="card p-5">
                <p className="text-sm font-bold text-brand-600 dark:text-brand-400">{s.step}</p>
                <h3 className="mt-2 font-semibold">{s.title}</h3>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Security */}
      <section id="security" className="border-t border-slate-200 bg-slate-50 py-16 dark:border-slate-800 dark:bg-slate-900/40">
        <div className="mx-auto max-w-4xl px-4 text-center">
          <h2 className="text-2xl font-bold sm:text-3xl">Security you can verify</h2>
          <ul className="mx-auto mt-6 grid max-w-3xl gap-3 text-left sm:grid-cols-2">
            {[
              'Argon2 password hashing and HttpOnly session cookies',
              'CSRF double-submit tokens on every mutation',
              'Credentials encrypted at rest with Fernet (AES-128-CBC + HMAC)',
              'Parser-based SQL validation, independent of the model',
              'Read-only database sessions with statement timeouts',
              'Row caps, response size limits and per-user rate limiting',
              'Per-resource ownership checks on every API route',
              'Destination policy blocking metadata and prohibited networks',
            ].map((item) => (
              <li key={item} className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-300">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
                {item}
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-slate-500">
            This application does not claim any security certification.
          </p>
        </div>
      </section>

      {/* Technology */}
      <section className="py-16">
        <div className="mx-auto max-w-4xl px-4 text-center">
          <h2 className="text-2xl font-bold sm:text-3xl">Technology</h2>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {['React', 'TypeScript', 'Vite', 'Tailwind CSS', 'TanStack Query', 'FastAPI', 'SQLAlchemy', 'PostgreSQL', 'Psycopg', 'Alembic', 'Ollama', 'Recharts', 'Pydantic', 'Argon2'].map(
              (t) => (
                <span
                  key={t}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                >
                  {t}
                </span>
              ),
            )}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-slate-200 bg-brand-600 py-14 text-white dark:border-slate-800">
        <div className="mx-auto max-w-3xl px-4 text-center">
          <h2 className="text-2xl font-bold sm:text-3xl">Ready to ask your database?</h2>
          <p className="mt-2 text-brand-100">
            Create an account, connect an authorized PostgreSQL database and start asking questions.
          </p>
          <Link
            to="/register"
            className="btn mt-6 bg-white px-6 py-3 text-base font-semibold text-brand-700 hover:bg-brand-50"
          >
            Create your account <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>
      </section>

      <footer className="border-t border-slate-200 py-8 dark:border-slate-800">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 text-sm text-slate-500 sm:flex-row">
          <p>© {new Date().getFullYear()} QueryMind AI. All rights reserved.</p>
          <p className="text-xs">Natural Language to SQL Intelligence Platform</p>
        </div>
      </footer>
    </div>
  );
}
