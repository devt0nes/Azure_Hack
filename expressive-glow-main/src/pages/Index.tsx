import { useEffect, useRef } from "react";
import { useThemeToggle } from "@/hooks/use-theme";

const PARTICLES = Array.from({ length: 20 }, (_, i) => ({
  id: i,
  left: Math.random() * 100,
  delay: Math.random() * 12,
  duration: 8 + Math.random() * 8,
  size: 1 + Math.random() * 2,
}));

const Index = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { theme, toggle: toggleTheme } = useThemeToggle();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let t = 0;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    const isLight = theme === "light";
    const lineColor = isLight ? "0, 0, 0" : "255, 255, 255";
    const lineBase = isLight ? 0.07 : 0.03;
    const lineDelta = isLight ? 0.02 : 0.01;

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const cols = Math.ceil(canvas.width / 80);
      const rows = Math.ceil(canvas.height / 80);

      for (let i = 0; i <= cols; i++) {
        const x = i * 80;
        const wave = Math.sin(t * 0.01 + i * 0.3) * 2;
        ctx.beginPath();
        ctx.moveTo(x + wave, 0);
        ctx.lineTo(x - wave, canvas.height);
        ctx.strokeStyle = `rgba(${lineColor}, ${lineBase + Math.sin(t * 0.005 + i) * lineDelta})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      for (let j = 0; j <= rows; j++) {
        const y = j * 80;
        const wave = Math.sin(t * 0.008 + j * 0.4) * 2;
        ctx.beginPath();
        ctx.moveTo(0, y + wave);
        ctx.lineTo(canvas.width, y - wave);
        ctx.strokeStyle = `rgba(${lineColor}, ${lineBase + Math.cos(t * 0.006 + j) * lineDelta})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      for (let i = 0; i <= cols; i++) {
        for (let j = 0; j <= rows; j++) {
          const brightness = Math.sin(t * 0.02 + i * 0.5 + j * 0.7) * 0.5 + 0.5;
          if (brightness > 0.7) {
            ctx.beginPath();
            ctx.arc(i * 80, j * 80, 1.5, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(242, 106, 46, ${brightness * 0.3})`;
            ctx.fill();
          }
        }
      }

      t++;
      animId = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, [theme]);

  return (
    <div className="min-h-screen bg-background text-foreground overflow-hidden relative">
      {/* Canvas wire grid */}
      <canvas ref={canvasRef} className="fixed inset-0 z-0 pointer-events-none" />

      {/* Grain texture overlay */}
      <div
        className="fixed inset-0 z-[1] pointer-events-none opacity-[0.035] animate-grain"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='1'/%3E%3C/svg%3E")`,
        }}
      />

      {/* Ambient glow blobs */}
      <div className="fixed inset-0 z-[1] pointer-events-none overflow-hidden">
        <div className="absolute -top-40 -left-40 w-[600px] h-[600px] rounded-full bg-primary/[0.06] blur-[120px] animate-drift" />
        <div className="absolute -bottom-40 -right-40 w-[500px] h-[500px] rounded-full bg-emerald-500/[0.04] blur-[100px] animate-drift-reverse" />
        <div className="absolute left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary/30 to-transparent animate-scan" />
      </div>

      {/* Rising particles */}
      <div className="fixed inset-0 z-[2] pointer-events-none overflow-hidden">
        {PARTICLES.map((p) => (
          <div
            key={p.id}
            className="absolute rounded-full bg-primary/40 animate-float-particle"
            style={{
              left: `${p.left}%`,
              width: `${p.size}px`,
              height: `${p.size}px`,
              animationDelay: `${p.delay}s`,
              animationDuration: `${p.duration}s`,
            }}
          />
        ))}
      </div>

      {/* Nav */}
      <nav className="relative z-10 px-6 py-5 border-b border-border/40">
        <div className="mx-auto max-w-7xl flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded border border-primary/40 bg-primary/10 flex items-center justify-center">
              <span className="text-primary font-bold text-xs mono">⌘</span>
            </div>
            <span className="mono text-xs uppercase tracking-[0.3em] text-foreground/60">
              agentic_nexus
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={toggleTheme}
              className="workshop-btn px-3 py-2 flex items-center gap-1.5"
              aria-label="Toggle theme"
            >
              {theme === "dark" ? (
                <span className="text-primary text-sm">☀</span>
              ) : (
                <span className="text-primary text-sm">☾</span>
              )}
            </button>
            <button className="workshop-link">
              Log in
            </button>
            <button className="btn-ember text-xs mono tracking-wider">
              Get Started →
            </button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative z-10 px-6 pt-28 pb-40">
        <div className="mx-auto max-w-5xl text-center">
          <div className="inline-flex items-center gap-3 mb-10 animate-fade-in opacity-0" style={{ animationDelay: "0.1s" }}>
            <span className="h-px w-8 bg-terminal/40" />
            <span className="w-1.5 h-1.5 rounded-full bg-terminal animate-pulse-glow" />
            <span className="mono text-[11px] uppercase tracking-[0.4em] text-terminal">
              Now in Beta
            </span>
            <span className="h-px w-8 bg-terminal/40" />
          </div>

          <h1
            className="font-display text-6xl md:text-7xl lg:text-[8.5rem] font-bold leading-[0.85] tracking-tight mb-10 animate-fade-in opacity-0 uppercase"
            style={{ animationDelay: "0.3s" }}
          >
            <span className="text-foreground/90">Agentic</span>
            <br />
            <span className="text-gradient-ember text-glow-ember">Nexus</span>
          </h1>

          <p
            className="text-sm md:text-base text-foreground/60 mb-14 max-w-lg mx-auto animate-fade-in-up opacity-0 leading-relaxed text-center"
            style={{ animationDelay: "0.5s" }}
          >
            Orchestrate teams of AI agents that work together to tackle complex projects — 
            with real-time progress tracking, smart task delegation, and full transparency.
          </p>

          <div className="flex items-center justify-center gap-4 animate-fade-in-up opacity-0" style={{ animationDelay: "0.7s" }}>
            <button className="btn-ember text-sm mono tracking-wider group">
              Start Free
              <span className="inline-block ml-2 transition-transform duration-300 group-hover:translate-x-1">→</span>
            </button>
            <button className="btn-wire mono text-xs tracking-wider">
              See How It Works
            </button>
          </div>

          {/* Live agent preview */}
          <div
            className="mt-16 mx-auto max-w-lg workshop-panel p-0 text-left animate-fade-in-up opacity-0"
            style={{ animationDelay: "0.9s" }}
          >
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/50 bg-secondary/30">
              <div className="w-2 h-2 rounded-full bg-destructive/50" />
              <div className="w-2 h-2 rounded-full bg-amber-500/50" />
              <div className="w-2 h-2 rounded-full bg-terminal/50" />
              <span className="mono text-[9px] text-muted-foreground/30 ml-auto">Agent Dashboard</span>
            </div>
            <div className="mono text-[11px] space-y-1.5 p-5">
              <p><span className="text-primary/70">▸</span> <span className="text-foreground/60">Starting project with 3 agents...</span></p>
              <p className="text-terminal/80">  ├─ Research Agent .............. <span className="text-terminal">ready</span></p>
              <p className="text-terminal/80">  ├─ Writing Agent ............... <span className="text-terminal">active</span></p>
              <p className="text-terminal/80">  ├─ Review Agent ................ <span className="text-terminal">active</span></p>
              <p className="text-terminal/80">  └─ Quality Check ............... <span className="text-terminal">queued</span></p>
              <p className="mt-2">
                <span className="text-primary/70">▸</span> <span className="text-foreground/40">Agents collaborating</span>
                <span className="animate-blink text-primary/80 ml-1">▊</span>
              </p>
            </div>
          </div>

          {/* Terminal snippet */}
          <div
            className="mt-16 mx-auto max-w-lg workshop-panel p-0 text-left animate-fade-in-up opacity-0"
            style={{ animationDelay: "0.9s" }}
          >
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/50 bg-secondary/30">
              <div className="w-2 h-2 rounded-full bg-destructive/50" />
              <div className="w-2 h-2 rounded-full bg-amber-500/50" />
              <div className="w-2 h-2 rounded-full bg-terminal/50" />
              <span className="mono text-[9px] text-muted-foreground/30 ml-auto">~/nexus/agents</span>
            </div>
            <div className="mono text-[11px] space-y-1.5 p-5">
              <p><span className="text-primary/70">λ</span> <span className="text-foreground/60">nexus init --agents 3 --mode workshop</span></p>
              <p className="text-terminal/80">  ├─ director_agent .............. <span className="text-terminal">ready</span></p>
              <p className="text-terminal/80">  ├─ worker_01 .................. <span className="text-terminal">spawned</span></p>
              <p className="text-terminal/80">  ├─ worker_02 .................. <span className="text-terminal">spawned</span></p>
              <p className="text-terminal/80">  └─ worker_03 .................. <span className="text-terminal">spawned</span></p>
              <p className="mt-2">
                <span className="text-primary/70">λ</span> <span className="text-foreground/40">_</span>
                <span className="animate-blink text-primary/80">▊</span>
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* How it Works */}
      <section className="relative z-10 px-6 py-24">
        <div className="mx-auto max-w-6xl">
          <div className="flex items-center gap-4 mb-4">
            <div className="h-px flex-1 bg-border" />
            <h2 className="mono text-xs uppercase tracking-[0.4em] text-muted-foreground">
              How It Works
            </h2>
            <div className="h-px flex-1 bg-border" />
          </div>
          <p className="text-center mono text-[11px] text-muted-foreground/40 mb-16">
            Three simple steps to get your AI team running
          </p>

          <div className="grid md:grid-cols-3 gap-px bg-border/50">
            {[
              {
                step: "01",
                fn: "describe",
                title: "Describe Your Goal",
                desc: "Tell the Director Agent what you want to build. It asks smart follow-up questions to fully understand your project before work begins.",
                status: "listening",
              },
              {
                step: "02",
                fn: "delegate",
                title: "Agents Get to Work",
                desc: "Your project is automatically broken into tasks and assigned to specialized AI agents — each an expert in their domain, working in parallel.",
                status: "working",
              },
              {
                step: "03",
                fn: "deliver",
                title: "Watch & Receive",
                desc: "Follow along in real-time as agents complete tasks. See live progress, track costs, and get your finished results as soon as they're ready.",
                status: "delivering",
              },
            ].map((item, i) => (
              <div key={i} className="workshop-card group">
                {/* Card header bar */}
                <div className="flex items-center justify-between mb-5 pb-3 border-b border-border/30">
                  <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-terminal animate-pulse-glow" />
                    <span className="mono text-[9px] text-terminal/70 uppercase tracking-widest">
                      phase_{item.step}
                    </span>
                  </div>
                  <span className="mono text-[9px] text-muted-foreground/30 tracking-wider">
                    {item.status}
                  </span>
                </div>
                {/* Function signature */}
                <p className="mono text-[10px] text-primary/50 mb-3">
                  {item.fn}
                </p>
                <h3 className="text-sm font-bold text-foreground mb-3 mono">{item.title}</h3>
                <p className="text-[11px] text-muted-foreground/60 leading-relaxed mono">{item.desc}</p>
                {/* Bottom progress bar */}
                <div className="mt-5 h-px w-full bg-border/30 relative overflow-hidden">
                  <div className="absolute inset-y-0 left-0 bg-primary/40 group-hover:animate-progress-fill" style={{ width: "0%" }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="relative z-10 px-6 py-24">
        <div className="mx-auto max-w-6xl">
          <div className="flex items-center gap-4 mb-4">
            <div className="h-px flex-1 bg-border" />
            <h2 className="mono text-xs uppercase tracking-[0.4em] text-muted-foreground">
              What You Get
            </h2>
            <div className="h-px flex-1 bg-border" />
          </div>
          <p className="text-center mono text-[11px] text-muted-foreground/40 mb-16">
            Powerful features, zero complexity
          </p>

          <div className="grid md:grid-cols-2 gap-px bg-border/50">
            {[
              { module: "workflows", label: "Visual Task Maps", desc: "See exactly how your project is broken down — which agents handle what, and how tasks connect to each other." },
              { module: "live_view", label: "Real-Time Progress", desc: "Watch your agents work in real time. Live updates show you exactly what's happening at every step." },
              { module: "budgets", label: "Built-In Cost Control", desc: "Know what you're spending before you spend it. Set budgets, get alerts, and never be surprised by a bill." },
              { module: "security", label: "Safe & Isolated", desc: "Every agent runs in its own secure environment. Your data stays private and agents can't interfere with each other." },
            ].map((item, i) => (
              <div key={i} className="workshop-card group">
                <div className="flex items-center gap-2 mb-4">
                  <span className="mono text-[9px] text-primary/40 bg-primary/5 border border-primary/10 px-2 py-0.5 rounded">
                    {item.module}
                  </span>
                  <span className="h-px flex-1 bg-border/20" />
                  <span className="w-1 h-1 rounded-full bg-terminal/50" />
                </div>
                <h3 className="mono text-sm font-bold text-foreground mb-2">{item.label}</h3>
                <p className="mono text-[11px] text-muted-foreground/50 leading-relaxed">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="relative z-10 px-6 py-24">
        <div className="mx-auto max-w-6xl">
          <div className="flex items-center gap-4 mb-4">
            <div className="h-px flex-1 bg-border" />
            <h2 className="mono text-xs uppercase tracking-[0.4em] text-muted-foreground">
              Pricing
            </h2>
            <div className="h-px flex-1 bg-border" />
          </div>
          <p className="text-center mono text-[11px] text-muted-foreground/40 mb-16">
            Pick the plan that fits your needs
          </p>

          <div className="grid md:grid-cols-3 gap-px bg-border/50">
            {/* Starter */}
            <div className="workshop-card">
              <div className="flex items-center justify-between mb-5 pb-3 border-b border-border/30">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/30" />
                  <span className="mono text-[9px] text-muted-foreground/40 uppercase tracking-widest">tier_01</span>
                </div>
                <span className="mono text-[9px] text-muted-foreground/20">free</span>
              </div>
              <p className="mono text-[10px] text-muted-foreground/30 mb-1">
                Starter
              </p>
              <div className="mb-6 mt-3">
                <span className="mono text-3xl font-black text-foreground">$0</span>
                <span className="mono text-xs text-muted-foreground/40 ml-1">/mo</span>
              </div>
              <div className="mono text-[11px] space-y-2 mb-8 text-muted-foreground/50">
                <p><span className="text-terminal/60">✓</span> 5 projects per month</p>
                <p><span className="text-terminal/60">✓</span> Basic agent teams</p>
                <p><span className="text-terminal/60">✓</span> Community support</p>
                <p className="text-muted-foreground/20"><span>✗</span> Priority speed</p>
                <p className="text-muted-foreground/20"><span>✗</span> Custom agents</p>
              </div>
              <button className="workshop-btn w-full">
                Get Started Free
              </button>
            </div>

            {/* Professional */}
            <div className="workshop-card workshop-card--highlighted relative">
              <div className="absolute -top-px left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary to-transparent" />
              <div className="flex items-center justify-between mb-5 pb-3 border-b border-primary/20">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse-glow" />
                  <span className="mono text-[9px] text-primary/60 uppercase tracking-widest">tier_02</span>
                </div>
                <span className="mono text-[9px] text-primary/40 bg-primary/5 border border-primary/10 px-2 py-0.5 rounded">
                  recommended
                </span>
              </div>
              <p className="mono text-[10px] text-muted-foreground/30 mb-1">
                Professional
              </p>
              <div className="mb-6 mt-3">
                <span className="mono text-3xl font-black text-gradient-ember">$49</span>
                <span className="mono text-xs text-muted-foreground/40 ml-1">/mo</span>
              </div>
              <div className="mono text-[11px] space-y-2 mb-8 text-muted-foreground/50">
                <p><span className="text-terminal">✓</span> Unlimited projects</p>
                <p><span className="text-terminal">✓</span> Advanced agent teams</p>
                <p><span className="text-terminal">✓</span> Priority support</p>
                <p><span className="text-terminal">✓</span> Faster processing</p>
                <p><span className="text-terminal">✓</span> Analytics dashboard</p>
              </div>
              <button className="btn-ember w-full mono text-xs tracking-wider">
                Start Pro Plan
              </button>
            </div>

            {/* Enterprise */}
            <div className="workshop-card">
              <div className="flex items-center justify-between mb-5 pb-3 border-b border-border/30">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/30" />
                  <span className="mono text-[9px] text-muted-foreground/40 uppercase tracking-widest">tier_03</span>
                </div>
                <span className="mono text-[9px] text-muted-foreground/20">custom</span>
              </div>
              <p className="mono text-[10px] text-muted-foreground/30 mb-1">
                Enterprise
              </p>
              <div className="mb-6 mt-3">
                <span className="mono text-3xl font-black text-foreground">Custom</span>
              </div>
              <div className="mono text-[11px] space-y-2 mb-8 text-muted-foreground/50">
                <p><span className="text-terminal/60">✓</span> Everything in Pro</p>
                <p><span className="text-terminal/60">✓</span> Dedicated infrastructure</p>
                <p><span className="text-terminal/60">✓</span> Custom-built agents</p>
                <p><span className="text-terminal/60">✓</span> Guaranteed uptime SLA</p>
                <p><span className="text-terminal/60">✓</span> White-label option</p>
              </div>
              <button className="workshop-btn w-full">
                Contact Sales
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="relative z-10 px-6 py-24">
        <div className="mx-auto max-w-3xl">
          <div className="workshop-panel p-10 text-center relative overflow-hidden">
            <div className="absolute inset-0 dot-grid opacity-30" />
            <div className="relative z-10">
              <p className="mono text-[10px] text-terminal/50 mb-4 uppercase tracking-widest">
                Ready to try it?
              </p>
              <h2 className="mono text-2xl md:text-3xl font-bold text-foreground mb-3">
                Start building with <span className="text-gradient-ember">Agentic Nexus</span>
              </h2>
              <p className="mono text-[11px] text-muted-foreground/40 mb-8 max-w-md mx-auto">
                Launch your first AI agent team in under 60 seconds. No credit card required.
              </p>
              <div className="flex items-center justify-center gap-3">
                <button className="btn-ember mono text-xs tracking-wider group">
                  Get Started Free
                  <span className="inline-block ml-2 transition-transform duration-300 group-hover:translate-x-1">→</span>
                </button>
                <button className="workshop-btn">
                  Read the Docs
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 px-6 py-10 border-t border-border/50">
        <div className="mx-auto max-w-6xl">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-3">
              <div className="w-5 h-5 rounded border border-primary/30 bg-primary/5 flex items-center justify-center">
                <span className="text-primary text-[8px] mono font-bold">⌘</span>
              </div>
              <span className="mono text-[10px] text-muted-foreground/30 uppercase tracking-[0.2em]">
                agentic_nexus
              </span>
            </div>
            <div className="flex items-center gap-6">
              {["Docs", "Changelog", "Status", "GitHub"].map((link) => (
                <a key={link} href="#" className="workshop-link">
                  {link}
                </a>
              ))}
            </div>
            <div className="flex items-center gap-4 mono text-[10px] text-muted-foreground/20">
              <span>© 2026</span>
              <span>v0.1.0-beta</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Index;
