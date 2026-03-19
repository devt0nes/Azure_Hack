import { useState } from 'react'

export default function LandingPage({ onLogin }) {
  const [authMode, setAuthMode] = useState(null)
  const [formValues, setFormValues] = useState({
    fullName: '',
    email: '',
    password: '',
    confirmPassword: '',
  })

  const openAuth = (mode) => setAuthMode(mode)
  const closeAuth = () => setAuthMode(null)

  const onChangeField = (event) => {
    const { name, value } = event.target
    setFormValues((prev) => ({ ...prev, [name]: value }))
  }

  const submitAuth = (event) => {
    event.preventDefault()
    onLogin()
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-sand via-white to-haze text-midnight overflow-hidden">
      {/* Animated background elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(242,106,46,0.15),_transparent_60%)]" />
        <div className="absolute -right-32 top-0 h-96 w-96 animate-float rounded-full bg-gradient-to-br from-ember/15 via-orange-400/10 to-transparent blur-3xl" />
        <div className="absolute -left-32 bottom-0 h-96 w-96 animate-float rounded-full bg-gradient-to-tr from-emerald-500/10 via-teal-400/5 to-transparent blur-3xl" style={{ animationDelay: '2s' }} />
      </div>

      {/* Navigation */}
      <nav className="relative z-10 px-6 py-6">
        <div className="mx-auto max-w-7xl flex items-center justify-between">
          <div className="flex items-center gap-2">
            <p className="mono text-sm uppercase tracking-[0.35em] bg-gradient-to-r from-ember to-orange-400 bg-clip-text text-transparent font-bold">
              PLATFORM A
            </p>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => openAuth('login')}
              className="px-6 py-2.5 text-sm font-semibold text-ink/80 hover:text-ink transition-colors"
            >
              Log In
            </button>
            <button
              onClick={() => openAuth('signup')}
              className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-ember to-orange-400 text-white text-sm font-bold hover:shadow-lg hover:scale-105 transition-all duration-300"
            >
              Sign Up
            </button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative z-10 px-6 pt-20 pb-32">
        <div className="mx-auto max-w-5xl text-center">
          <p className="mono text-sm uppercase tracking-[0.35em] bg-gradient-to-r from-ember to-orange-400 bg-clip-text text-transparent mb-6 animate-fade-in">
            Multi-Agent Orchestration Platform
          </p>
          <h1 className="text-6xl md:text-7xl lg:text-8xl font-bold bg-gradient-to-r from-midnight via-ink to-midnight bg-clip-text text-transparent mb-8 animate-fade-in leading-tight">
            Command Center
          </h1>
          <p className="text-xl md:text-2xl text-ink/70 mb-12 max-w-3xl mx-auto animate-fade-in-up leading-relaxed">
            Orchestrate autonomous AI agents with intelligent task delegation, real-time monitoring, and live execution insights.
          </p>
          <button
            onClick={() => openAuth('signup')}
            className="px-10 py-4 rounded-xl bg-gradient-to-r from-ember to-orange-400 text-white text-lg font-bold hover:shadow-2xl hover:scale-105 transition-all duration-300 animate-fade-in-up"
          >
            Get Started
          </button>
        </div>
      </section>

      {/* Workflow Section */}
      <section className="relative z-10 px-6 py-20 bg-gradient-to-b from-transparent via-white/50 to-transparent">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-midnight via-ink to-midnight bg-clip-text text-transparent text-center mb-16">
            How It Works
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            <div className="rounded-3xl border border-white/30 bg-gradient-to-br from-white/80 via-white/60 to-white/40 p-8 backdrop-blur-md shadow-glass hover:shadow-xl transition-all duration-300">
              <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-ember to-orange-400 flex items-center justify-center mb-6">
                <svg className="h-6 w-6 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
                </svg>
              </div>
              <h3 className="text-xl font-bold text-ink mb-4">1. Direct & Clarify</h3>
              <p className="text-ink/70 leading-relaxed">
                Communicate with the Director Agent to define your project requirements. It intelligently clarifies ambiguities and builds a complete task understanding.
              </p>
            </div>

            <div className="rounded-3xl border border-white/30 bg-gradient-to-br from-white/80 via-white/60 to-white/40 p-8 backdrop-blur-md shadow-glass hover:shadow-xl transition-all duration-300">
              <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-amber-500 to-orange-400 flex items-center justify-center mb-6">
                <svg className="h-6 w-6 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <circle cx="6" cy="6" r="2" />
                  <circle cx="18" cy="6" r="2" />
                  <circle cx="12" cy="18" r="2" />
                  <path d="M8 7l3 9" />
                  <path d="M16 7l-3 9" />
                  <path d="M8 6h8" />
                </svg>
              </div>
              <h3 className="text-xl font-bold text-ink mb-4">2. Orchestrate Agents</h3>
              <p className="text-ink/70 leading-relaxed">
                The system generates an Agent Execution Graph (AEG), delegating specialized tasks to expert agents with optimal dependency management.
              </p>
            </div>

            <div className="rounded-3xl border border-white/30 bg-gradient-to-br from-white/80 via-white/60 to-white/40 p-8 backdrop-blur-md shadow-glass hover:shadow-xl transition-all duration-300">
              <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-500 flex items-center justify-center mb-6">
                <svg className="h-6 w-6 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M13 2L3 14h7l-1 8 10-12h-7z" />
                </svg>
              </div>
              <h3 className="text-xl font-bold text-ink mb-4">3. Monitor & Execute</h3>
              <p className="text-ink/70 leading-relaxed">
                Watch real-time execution with live logs, cost tracking, and progress monitoring. Get instant feedback and preview results as agents complete tasks.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Subscription Section */}
      <section className="relative z-10 px-6 py-20">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-midnight via-ink to-midnight bg-clip-text text-transparent text-center mb-6">
            Choose Your Plan
          </h2>
          <p className="text-center text-ink/70 text-lg mb-16 max-w-2xl mx-auto">
            Start with our free tier or scale with professional features for production workloads.
          </p>
          
          <div className="grid md:grid-cols-3 gap-8">
            {/* Free Tier */}
            <div className="rounded-3xl border border-white/30 bg-gradient-to-br from-white/60 via-white/40 to-white/20 p-8 backdrop-blur-md shadow-glass hover:shadow-xl transition-all duration-300">
              <h3 className="text-2xl font-bold text-ink mb-2">Starter</h3>
              <div className="mb-6">
                <span className="text-4xl font-bold text-ink">$0</span>
                <span className="text-ink/70 ml-2">/month</span>
              </div>
              <ul className="space-y-3 mb-8 text-ink/70">
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>5 projects per month</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Basic agent orchestration</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Community support</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-ink/40 mt-1">Not included</span>
                  <span className="text-ink/40">Priority execution</span>
                </li>
              </ul>
              <button
                onClick={() => openAuth('signup')}
                className="w-full px-6 py-3 rounded-xl border-2 border-ink/20 text-ink font-semibold hover:border-ink/40 hover:bg-ink/5 transition-all duration-300"
              >
                Start Free
              </button>
            </div>

            {/* Pro Tier */}
            <div className="rounded-3xl border-2 border-ember/30 bg-gradient-to-br from-white/90 via-white/70 to-white/50 p-8 backdrop-blur-md shadow-xl hover:shadow-2xl transition-all duration-300 relative">
              <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1.5 rounded-full bg-gradient-to-r from-ember to-orange-400 text-white text-xs font-bold uppercase tracking-wider">
                Popular
              </div>
              <h3 className="text-2xl font-bold text-ink mb-2">Professional</h3>
              <div className="mb-6">
                <span className="text-4xl font-bold bg-gradient-to-r from-ember to-orange-400 bg-clip-text text-transparent">$49</span>
                <span className="text-ink/70 ml-2">/month</span>
              </div>
              <ul className="space-y-3 mb-8 text-ink/70">
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Unlimited projects</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Advanced agent orchestration</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Priority support</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Priority execution queue</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Advanced analytics</span>
                </li>
              </ul>
              <button
                onClick={() => openAuth('signup')}
                className="w-full px-6 py-3 rounded-xl bg-gradient-to-r from-ember to-orange-400 text-white font-bold hover:shadow-lg hover:scale-105 transition-all duration-300"
              >
                Start Pro Trial
              </button>
            </div>

            {/* Enterprise Tier */}
            <div className="rounded-3xl border border-white/30 bg-gradient-to-br from-white/60 via-white/40 to-white/20 p-8 backdrop-blur-md shadow-glass hover:shadow-xl transition-all duration-300">
              <h3 className="text-2xl font-bold text-ink mb-2">Enterprise</h3>
              <div className="mb-6">
                <span className="text-4xl font-bold text-ink">Custom</span>
              </div>
              <ul className="space-y-3 mb-8 text-ink/70">
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Everything in Pro</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Dedicated infrastructure</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>Custom agent development</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>SLA guarantees</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-1">Included</span>
                  <span>White-label options</span>
                </li>
              </ul>
              <button
                onClick={() => openAuth('signup')}
                className="w-full px-6 py-3 rounded-xl border-2 border-ink/20 text-ink font-semibold hover:border-ink/40 hover:bg-ink/5 transition-all duration-300"
              >
                Contact Sales
              </button>
            </div>
          </div>
        </div>
      </section>

      {authMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-midnight/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-white/40 bg-white/95 p-6 shadow-2xl">
            <div className="mb-5 flex items-center justify-between">
              <h3 className="text-xl font-bold text-ink">
                {authMode === 'login' ? 'Log In' : 'Create Account'}
              </h3>
              <button
                onClick={closeAuth}
                className="rounded-md bg-ink/5 px-2.5 py-1.5 text-sm text-ink/70 hover:bg-ink/10"
              >
                Close
              </button>
            </div>

            <form onSubmit={submitAuth} className="space-y-4">
              {authMode === 'signup' && (
                <div>
                  <label className="mb-1 block text-sm font-medium text-ink/80">Full name</label>
                  <input
                    name="fullName"
                    value={formValues.fullName}
                    onChange={onChangeField}
                    required
                    className="w-full rounded-lg border border-ink/15 bg-white px-3 py-2 text-sm outline-none transition focus:border-ember/60"
                    placeholder="Jane Doe"
                  />
                </div>
              )}

              <div>
                <label className="mb-1 block text-sm font-medium text-ink/80">Email</label>
                <input
                  type="email"
                  name="email"
                  value={formValues.email}
                  onChange={onChangeField}
                  required
                  className="w-full rounded-lg border border-ink/15 bg-white px-3 py-2 text-sm outline-none transition focus:border-ember/60"
                  placeholder="you@company.com"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-ink/80">Password</label>
                <input
                  type="password"
                  name="password"
                  value={formValues.password}
                  onChange={onChangeField}
                  required
                  className="w-full rounded-lg border border-ink/15 bg-white px-3 py-2 text-sm outline-none transition focus:border-ember/60"
                  placeholder="••••••••"
                />
              </div>

              {authMode === 'signup' && (
                <div>
                  <label className="mb-1 block text-sm font-medium text-ink/80">Confirm password</label>
                  <input
                    type="password"
                    name="confirmPassword"
                    value={formValues.confirmPassword}
                    onChange={onChangeField}
                    required
                    className="w-full rounded-lg border border-ink/15 bg-white px-3 py-2 text-sm outline-none transition focus:border-ember/60"
                    placeholder="••••••••"
                  />
                </div>
              )}

              <button
                type="submit"
                className="w-full rounded-xl bg-gradient-to-r from-ember to-orange-400 px-4 py-2.5 text-sm font-bold text-white transition hover:shadow-lg"
              >
                {authMode === 'login' ? 'Continue to Command Center' : 'Create account and continue'}
              </button>
            </form>

            <p className="mt-4 text-xs text-ink/55">
              Local session mode: sign-in input is used for this browser session only.
            </p>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="relative z-10 px-6 py-12 border-t border-white/20">
        <div className="mx-auto max-w-6xl text-center">
          <p className="text-sm text-ink/60">Platform A Command Center • March 2026</p>
        </div>
      </footer>
    </div>
  )
}
