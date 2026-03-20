import { loginWithGoogle } from '../firebaseConfig'
import AnimatedGridBackground from '../components/AnimatedGridBackground.jsx'
import { useState, useEffect, useRef } from 'react'

const FAQ_ITEMS = [
  {
    id: 'why-exists',
    icon: '◆',
    question: 'Why Agentic Nexus exists',
    answer:
      'Many great ideas never get built because people must learn prompting, backend, cloud setup, CI/CD, and monitoring all at once. We remove every gate between idea and production.',
  },
  {
    id: 'what-it-does',
    icon: '▸',
    question: 'What Agentic Nexus does',
    answer:
      'You describe your app in plain language. A Director AI plans the work, then specialized agents build in parallel to produce a tested, deployment-ready app with infrastructure templates and CI/CD wired in.',
  },
  {
    id: 'what-today',
    icon: '✓',
    question: 'What you can use today',
    answer:
      'Live Director chat, Agent Execution Graph (AEG) view, real-time logs and cost tracking, generated app preview in Docker or Azure, Learning Mode tutor support, and direct Copilot IDE integration.',
  },
  {
    id: 'how-agents-work',
    icon: '◎',
    question: 'How do the agents work together',
    answer:
      'Agents form a directed graph where each node is a specialist (Backend Engineer, Frontend Engineer, Database Architect, etc). They communicate via named channels, share context in real-time, and run in parallel. A Director AI orchestrates the entire flow.',
  },
  {
    id: 'output',
    icon: '◉',
    question: 'What do I get at the end',
    answer:
      'A complete production-ready bundle: Docker image, Bicep/ARM infrastructure templates, unit & integration tests, GitHub Actions CI/CD pipeline, comprehensive README, generated app code, and an optional Learning Mode walkthrough explaining every decision.',
  },
]

const SIMPLE_WORKFLOW = [
  {
    step: '1',
    icon: '▪',
    title: 'Tell us your idea',
    text: 'Describe what you want to build in everyday language.',
  },
  {
    step: '2',
    icon: '◆',
    title: 'Get a clear plan',
    text: 'The Director AI asks follow-up questions and creates a practical build plan.',
  },
  {
    step: '3',
    icon: '▸',
    title: 'Agents build together',
    text: 'Specialized agents work in parallel while you watch progress live.',
  },
  {
    step: '4',
    icon: '✓',
    title: 'Preview and deploy',
    text: 'Review generated output, then deploy to Azure in guided steps.',
  },
]

// Custom hook for scroll animation
const useScrollAnimation = () => {
  const ref = useRef(null)
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true)
          observer.unobserve(entry.target)
        }
      },
      { threshold: 0.1, rootMargin: '0px 0px -50px 0px' }
    )

    if (ref.current) {
      observer.observe(ref.current)
    }

    return () => {
      if (ref.current) {
        observer.unobserve(ref.current)
      }
    }
  }, [])

  return [ref, isVisible]
}

const LIVE_METRICS = [
  { label: 'Agent Roles', value: '9+' },
  { label: 'Build Stages', value: '7' },
  { label: 'Live Dashboards', value: 'AEG + Logs' },
  { label: 'Deploy Mode', value: 'One-Click' },
]

export default function LandingPage({ onLogin, theme, onToggleTheme }) {
  const [expandedFAQ, setExpandedFAQ] = useState(null)
  const [workflowRef, workflowVisible] = useScrollAnimation()
  const [faqRef, faqVisible] = useScrollAnimation()
  const [metricsRef, metricsVisible] = useScrollAnimation()
  const [tickerRef, tickerVisible] = useScrollAnimation()
  const [pricingRef, pricingVisible] = useScrollAnimation()

  const handleLogin = async () => {
    try {
      const { user, token } = await loginWithGoogle()
      onLogin(user, token)
    } catch (err) {
      console.error('Login failed', err)
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
      <AnimatedGridBackground theme={theme} />

      <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <div className="absolute -top-40 -left-40 h-[600px] w-[600px] animate-drift rounded-full bg-primary/[0.06] blur-[120px]" />
        <div className="absolute -bottom-40 -right-40 h-[500px] w-[500px] animate-drift-reverse rounded-full bg-emerald-500/[0.04] blur-[100px]" />
        <div className="absolute left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary/30 to-transparent animate-scan" />
      </div>

      <div
        className="pointer-events-none fixed inset-0 z-[1] opacity-[0.035] animate-grain"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='1'/%3E%3C/svg%3E\")",
        }}
      />

      <nav className="relative z-10 border-b border-border/40 px-6 py-5">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <p className="mono text-sm uppercase tracking-[0.32em] text-foreground/80">Agentic_Nexus</p>
          <div className="flex items-center gap-4">
            <button
              onClick={onToggleTheme}
              className="workshop-btn px-3 py-2"
              aria-label="Toggle theme"
              title="Toggle theme"
            >
              <span className="text-sm">{theme === 'dark' ? '☀' : '☾'}</span>
            </button>
            <button onClick={handleLogin} className="mono text-xs font-semibold uppercase tracking-[0.22em] text-foreground/75 transition-colors hover:text-foreground">Log In</button>
            <button onClick={handleLogin} className="btn-ember mono rounded-sm px-6 py-2 text-xs tracking-wider">Get Started</button>
          </div>
        </div>
      </nav>

      <section className="relative z-10 px-6 pb-24 pt-20">
        <div className="mx-auto max-w-5xl text-center">
          <p className="mono mb-6 text-sm font-semibold uppercase tracking-[0.35em] text-terminal">Multi-Agent Orchestration Platform</p>
          <h1 className="font-display text-7xl font-bold uppercase leading-[0.9] tracking-tight md:text-8xl lg:text-9xl">
            <span className="text-foreground/90">Agentic</span>
            <br />
            <span className="text-gradient-ember text-glow-ember">Nexus</span>
          </h1>
          <p className="mx-auto mb-12 mt-8 max-w-3xl text-lg font-medium text-foreground/80 md:text-xl">
            Orchestrate your team of AI agents. From idea to production-ready application in one intelligent workflow.
          </p>
          <button onClick={handleLogin} className="btn-ember mono rounded-sm px-10 py-3 text-sm tracking-wider">Start Free →</button>

          <div ref={metricsRef} className={`mx-auto mt-10 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-4 transition-all duration-700 ${metricsVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
            {LIVE_METRICS.map((metric) => (
              <div
                key={metric.label}
                className="group rounded-xl border border-border bg-gradient-to-br from-card/95 via-card/85 to-surface-raised/70 p-4 text-left shadow-glass transition-all duration-300 hover:-translate-y-1 hover:border-primary/35"
              >
                <p className="mono text-[11px] uppercase tracking-[0.2em] text-foreground/55">{metric.label}</p>
                <p className="mt-2 text-lg font-bold text-foreground group-hover:text-primary">{metric.value}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section ref={tickerRef} className={`relative z-10 px-6 pb-8 transition-all duration-700 ${tickerVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
        <div className="mx-auto max-w-6xl overflow-hidden rounded-xl border border-border bg-card/80 py-3">
          <div className="animate-ticker flex min-w-max items-center gap-10 px-6">
            {[
              'Director AI Clarification Loop',
              'Parallel Multi-Agent Execution',
              'Live Cost & Token Tracking',
              'Agent Execution Graph (AEG)',
              'Generated App Preview',
              'Guided Azure Deployment',
              'Director AI Clarification Loop',
              'Parallel Multi-Agent Execution',
              'Live Cost & Token Tracking',
              'Agent Execution Graph (AEG)',
              'Generated App Preview',
              'Guided Azure Deployment',
            ].map((item, idx) => (
              <div key={`${item}-${idx}`} className="flex items-center gap-3">
                <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                <span className="mono text-xs uppercase tracking-[0.2em] text-foreground/65">{item}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section ref={workflowRef} className={`relative z-10 px-6 py-20 transition-all duration-700 ${workflowVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
        <div className="mx-auto max-w-6xl">
          <div className="mb-12 text-center">
            <h2 className="text-4xl md:text-5xl font-bold text-foreground mb-3 tracking-tight">Workflow</h2>
            <p className="mx-auto max-w-2xl text-base font-medium text-foreground/70">
              How your idea becomes production-ready software.
            </p>
          </div>
          <div className="mx-auto max-w-2xl space-y-4">
            {SIMPLE_WORKFLOW.map((item, index) => (
              <div key={item.step} className="relative">
                <div className="rounded-xl border border-border bg-gradient-to-br from-card/95 via-card/85 to-surface-raised/70 p-6 shadow-glass">
                  <div className="flex items-start gap-4">
                    <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-md border border-primary/30 bg-primary/10 mono text-lg font-bold text-primary">
                      {item.icon}
                    </div>
                    <div className="flex-1">
                      <span className="mono text-[10px] uppercase tracking-[0.2em] text-foreground/50">Step {item.step}</span>
                      <h3 className="mono mt-1 text-lg font-bold text-foreground">{item.title}</h3>
                      <p className="mt-2 text-sm leading-relaxed text-foreground/80">{item.text}</p>
                    </div>
                  </div>
                </div>
                {index < SIMPLE_WORKFLOW.length - 1 && (
                  <div className="flex justify-center py-2">
                    <span className="mono text-2xl text-primary/70">↓</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="relative z-10 px-6 py-16">
        <div className="mx-auto max-w-3xl">
          <div className="workshop-panel p-0 text-left">
            <div className="flex items-center gap-2 border-b border-border/50 bg-gradient-to-r from-primary/15 to-transparent px-4 py-2.5">
              <div className="h-2 w-2 rounded-full bg-destructive/50" />
              <div className="h-2 w-2 rounded-full bg-amber-500/50" />
              <div className="h-2 w-2 rounded-full bg-terminal/50" />
              <span className="mono ml-auto text-[9px] text-muted-foreground/30">Agent Execution Terminal</span>
            </div>
            <div className="mono space-y-1.5 p-5 text-[11px]">
              <p>
                <span className="text-primary/70">▸</span> <span className="text-foreground/60">Initializing project deployment...</span>
              </p>
              <p className="text-terminal/80">
                  ├─ Director Agent <span className="text-terminal">........................... ready</span>
              </p>
              <p className="text-terminal/80">
                  ├─ Frontend Engineer <span className="text-terminal">..................... active</span>
              </p>
              <p className="text-terminal/80">
                  ├─ Backend Engineer <span className="text-terminal">..................... active</span>
              </p>
              <p className="text-terminal/80">
                  ├─ DevOps & Cloud <span className="text-terminal">........................ active</span>
              </p>
              <p className="text-terminal/80">
                  └─ Quality Assurance <span className="text-terminal">..................... queued</span>
              </p>
              <p className="mt-2">
                <span className="text-primary/70">▸</span>{' '}
                <span className="text-foreground/40">Agents collaborating on build</span>
                <span className="animate-blink text-primary/80 ml-1">▊</span>
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="relative z-10 px-6 py-20">
        <div className="mx-auto max-w-6xl">
          <div className="mb-12 text-center">
            <h2 className="text-4xl md:text-5xl font-bold text-foreground mb-3 tracking-tight">How It Works</h2>
            <p className="mx-auto max-w-2xl text-base font-medium text-foreground/70">
              Three stages to build your application.
            </p>
          </div>
          <div className="grid gap-px bg-border/50 md:grid-cols-3">
            <div className="workshop-card group relative overflow-hidden">
              <div className="absolute inset-0 -z-10 rounded opacity-0 transition-opacity group-hover:opacity-100 bg-gradient-to-br from-primary/15 to-transparent pointer-events-none" />
              <p className="mono text-xs font-semibold text-primary/70">01 / clarify</p>
              <h3 className="mono mt-3 text-base font-bold text-foreground">Direct & Clarify</h3>
              <p className="mono mt-3 text-[13px] leading-relaxed text-foreground/75">Communicate with the Director Agent to define project requirements and resolve ambiguities interactively.</p>
            </div>
            <div className="workshop-card group relative overflow-hidden">
              <div className="absolute inset-0 -z-10 rounded opacity-0 transition-opacity group-hover:opacity-100 bg-gradient-to-br from-emerald-500/15 to-transparent pointer-events-none" />
              <p className="mono text-xs font-semibold text-emerald-600 dark:text-emerald-400">02 / delegate</p>
              <h3 className="mono mt-3 text-base font-bold text-foreground">Orchestrate Agents</h3>
              <p className="mono mt-3 text-[13px] leading-relaxed text-foreground/75">The system builds an Agent Execution Graph and delegates tasks to specialized agents working in parallel.</p>
            </div>
            <div className="workshop-card group relative overflow-hidden">
              <div className="absolute inset-0 -z-10 rounded opacity-0 transition-opacity group-hover:opacity-100 bg-gradient-to-br from-blue-500/15 to-transparent pointer-events-none" />
              <p className="mono text-xs font-semibold text-blue-700 dark:text-blue-400">03 / monitor</p>
              <h3 className="mono mt-3 text-base font-bold text-foreground">Monitor & Execute</h3>
              <p className="mono mt-3 text-[13px] leading-relaxed text-foreground/75">Track live logs, costs, and progress while generated output becomes available in real time.</p>
            </div>
          </div>
        </div>
      </section>

      <section ref={pricingRef} className={`relative z-10 px-6 py-20 transition-all duration-700 ${pricingVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
        <div className="mx-auto max-w-6xl">
          <div className="mb-12 text-center">
            <h2 className="text-4xl md:text-5xl font-bold text-foreground mb-3 tracking-tight">Pricing</h2>
            <p className="mx-auto max-w-2xl text-base font-medium text-foreground/70">
              Choose the plan that fits your building pace. You only pay for what you use.
            </p>
          </div>
          <div className="grid gap-px bg-border/50 md:grid-cols-3">
            <div className="workshop-card group relative">
              <div className="absolute inset-0 -z-10 rounded opacity-0 transition-opacity group-hover:opacity-100 bg-gradient-to-br from-blue-500/10 to-transparent pointer-events-none" />
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-border/30">
                <h3 className="mono text-xs font-semibold text-foreground/70">STARTER</h3>
                <span className="mono text-[9px] text-muted-foreground/40">free plan</span>
              </div>
              <p className="mono text-2xl font-black text-foreground mb-1">$0<span className="text-xs text-foreground/55 ml-1 font-normal">/month</span></p>
              <p className="mono text-[11px] text-foreground/60 mb-6">Perfect for learning</p>
              <ul className="mono text-[11px] space-y-2 mb-8 text-foreground/70">
                <li>✓ 1 free build per month</li>
                <li>✓ Local preview only</li>
                <li>✓ Community support</li>
                <li className="text-muted-foreground/50">✗ Azure deployment</li>
                <li className="text-muted-foreground/50">✗ Learning Mode tutor</li>
              </ul>
              <button onClick={handleLogin} className="workshop-btn w-full">Get Started</button>
            </div>

            <div className="workshop-card workshop-card--highlighted group relative border-primary/40">
              <div className="absolute -top-px left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary to-transparent" />
              <div className="absolute inset-0 -z-10 rounded opacity-0 transition-opacity group-hover:opacity-100 bg-gradient-to-br from-primary/15 to-transparent pointer-events-none" />
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-primary/20">
                <h3 className="mono text-xs font-semibold text-primary/80">PROFESSIONAL</h3>
                <span className="mono text-[9px] text-primary/50 bg-primary/10 px-2 py-0.5 rounded">recommended</span>
              </div>
              <p className="mono text-2xl font-black text-gradient-ember mb-1">$99<span className="text-xs text-foreground/55 ml-1 font-normal">/month</span></p>
              <p className="mono text-[11px] text-foreground/60 mb-6">For active builders</p>
              <ul className="mono text-[11px] space-y-2 mb-8 text-foreground/70">
                <li>✓ Unlimited builds</li>
                <li>✓ Cloud & local preview</li>
                <li>✓ Azure one-click deploy</li>
                <li>✓ Learning Mode tutor</li>
                <li>✓ Priority support</li>
              </ul>
              <button onClick={handleLogin} className="btn-ember w-full rounded-sm py-3 mono text-xs tracking-wider">Start Pro Trial</button>
            </div>

            <div className="workshop-card group relative">
              <div className="absolute inset-0 -z-10 rounded opacity-0 transition-opacity group-hover:opacity-100 bg-gradient-to-br from-emerald-500/10 to-transparent pointer-events-none" />
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-border/30">
                <h3 className="mono text-xs font-semibold text-foreground/70">ENTERPRISE</h3>
                <span className="mono text-[9px] text-muted-foreground/40">custom</span>
              </div>
              <p className="mono text-2xl font-black text-foreground mb-1">Volume<span className="text-xs text-foreground/55 ml-1 font-normal">pricing</span></p>
              <p className="mono text-[11px] text-foreground/60 mb-6">For teams & orgs</p>
              <ul className="mono text-[11px] space-y-2 mb-8 text-foreground/70">
                <li>✓ Everything in Pro</li>
                <li>✓ Team collaboration</li>
                <li>✓ SLA & dedicated support</li>
                <li>✓ Custom agent training</li>
                <li>✓ White-label option</li>
              </ul>
              <button onClick={handleLogin} className="workshop-btn w-full">Contact Sales</button>
            </div>
          </div>
          <p className="mt-8 text-center mono text-[11px] text-foreground/50">
            All plans include Azure infrastructure costs billed separately. Pricing subject to our terms of service.
          </p>
        </div>
      </section>

      <section ref={faqRef} className={`relative z-10 px-6 py-20 transition-all duration-700 ${faqVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
        <div className="mx-auto max-w-4xl">
          <div className="mb-12 text-center">
            <h2 className="text-4xl md:text-5xl font-bold text-foreground mb-3 tracking-tight">FAQ</h2>
            <p className="mx-auto max-w-2xl text-base font-medium text-foreground/70">
              Questions answered about Agentic Nexus.
            </p>
          </div>
          <div className="space-y-3">
            {FAQ_ITEMS.map((item) => (
              <div
                key={item.id}
                className="overflow-hidden rounded-xl border border-border bg-gradient-to-br from-card/95 via-card/88 to-surface-raised/72"
              >
                <button
                  onClick={() => setExpandedFAQ(expandedFAQ === item.id ? null : item.id)}
                  className="w-full px-6 py-4 text-left transition-all hover:bg-surface-raised/50"
                >
                  <div className="flex items-start gap-4">
                    <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md border border-primary/30 bg-primary/10 mono text-base font-bold text-primary">
                      {item.icon}
                    </span>
                    <div className="flex-1">
                      <h3 className="mono text-base font-bold text-foreground">{item.question}</h3>
                    </div>
                    <span className="mono text-primary/70 transition-transform duration-300" style={{ transform: expandedFAQ === item.id ? 'rotate(180deg)' : 'rotate(0deg)' }}>
                      ▼
                    </span>
                  </div>
                </button>
                <div className={`overflow-hidden transition-all duration-300 ${expandedFAQ === item.id ? 'max-h-96' : 'max-h-0'}`}>
                  <div className="border-t border-border/30 bg-surface-raised/30 px-6 py-4">
                    <p className="text-sm leading-relaxed text-foreground/80">{item.answer}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="relative z-10 border-t border-border/40 px-6 py-12">
        <div className="mx-auto max-w-6xl text-center">
          <p className="mono text-sm text-foreground/65">Platform A Command Center • March 2026</p>
        </div>
      </footer>
    </div>
  )
}
