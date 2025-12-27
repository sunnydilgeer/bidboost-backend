// app/(public)/pricing/page.tsx
import Link from "next/link";
import { Check, Sparkles } from "lucide-react";

export default function PricingPage() {
  return (
    <div className="bg-white">
      {/* HERO */}
      <section className="pt-20 pb-12 bg-gradient-to-b from-blue-50 to-white">
        <div className="max-w-5xl mx-auto px-6 text-center">
          <span className="inline-flex items-center gap-1 px-3 py-1 text-xs font-semibold bg-blue-100 text-blue-700 rounded-full mb-4">
            <Sparkles className="w-3 h-3" />
            Pricing
          </span>

          <h1 className="text-4xl sm:text-5xl font-bold text-gray-900 mb-4 leading-tight">
            Find the federal contracts worth pursuing —{" "}
            <span className="text-blue-600">without the noise</span>
          </h1>

          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            BidMatch uses AI to match your real capabilities to live SAM.gov
            opportunities, so you can focus on contracts you actually have a shot
            at winning.
          </p>

          <p className="mt-3 text-sm text-gray-600">
            <span className="font-semibold text-gray-900">
              No scraping. No keyword guessing. No spreadsheets.
            </span>
          </p>

          <div className="mt-8 flex flex-col sm:flex-row justify-center gap-3">
            <Link
              href="/signup?plan=pro"
              className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition"
            >
              Get started with Pro
            </Link>

            <Link
              href="/signup?plan=starter"
              className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-white text-gray-700 font-semibold rounded-lg border-2 border-gray-200 hover:border-gray-300 transition"
            >
              Start with Starter
            </Link>
          </div>

          <div className="mt-4 text-sm text-gray-600">
            Want to try it first?{" "}
            <Link href="/quick-start-flow" className="text-blue-600 font-semibold">
              Run a free website scan
            </Link>
            .
          </div>
        </div>
      </section>

      {/* PRICING CARDS */}
      <section className="py-14 bg-white">
        <div className="max-w-5xl mx-auto px-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
            {/* Starter */}
            <div className="bg-white rounded-xl border-2 border-gray-200 p-6 flex flex-col">
              <div className="flex items-start justify-between gap-6">
                <div>
                  <h2 className="text-xl font-bold text-gray-900">Starter</h2>
                  <p className="mt-1 text-sm text-gray-600">
                    For solo founders and very small firms
                  </p>
                </div>

                <div className="text-right">
                  <div className="text-3xl font-bold text-gray-900">$99</div>
                  <div className="text-sm text-gray-600">/ month</div>
                </div>
              </div>

              <p className="mt-4 text-sm text-gray-700">
                Starter helps you find relevant federal contracts without the noise.
              </p>

              <div className="mt-5 space-y-3 text-sm text-gray-800">
                <Feature>AI matching from company website (Quick Start)</Feature>
                <Feature>Personalized contract feed sorted by match score</Feature>
                <Feature>Search SAM.gov contracts</Feature>
                <Feature>
                  Basic filters (min match score, U.S. state)
                </Feature>
                <Feature>View contract details (agency, NAICS, due date, value when available)</Feature>
                <Feature>Save/bookmark contracts (up to 50)</Feature>
                <Feature>Daily email digest (9:00 AM Eastern)</Feature>
              </div>

              <div className="mt-6 border-t pt-5">
                <div className="text-xs font-semibold text-gray-500 uppercase">
                  Not included
                </div>
                <ul className="mt-3 space-y-2 text-sm text-gray-600">
                  <li>Dashboard KPIs & prioritization</li>
                  <li>Deadline urgency indicators</li>
                  <li>Pipeline statuses (Pursue / Monitor / Pass)</li>
                  <li>Notes</li>
                  <li>AI positioning recommendations</li>
                  <li>Advanced capability refinement</li>
                </ul>
              </div>

              <div className="mt-6 mt-auto">
                <Link
                  href="/signup?plan=starter"
                  className="inline-flex w-full items-center justify-center px-6 py-3 bg-white text-gray-700 font-semibold rounded-lg border-2 border-gray-200 hover:border-gray-300 transition"
                >
                  Start with Starter
                </Link>
              </div>
            </div>

            {/* Pro */}
            <div className="bg-white rounded-xl border-2 border-blue-200 p-6 flex flex-col">
              <div className="flex items-start justify-between gap-6">
                <div>
                  <span className="inline-flex items-center gap-1 px-3 py-1 text-xs font-semibold bg-blue-100 text-blue-700 rounded-full mb-3">
                    <Sparkles className="w-3 h-3" />
                    Recommended
                  </span>

                  <h2 className="text-xl font-bold text-gray-900">Pro</h2>
                  <p className="mt-1 text-sm text-gray-600">
                    For firms actively bidding
                  </p>
                </div>

                <div className="text-right">
                  <div className="text-3xl font-bold text-gray-900">$149</div>
                  <div className="text-sm text-gray-600">/ month</div>
                </div>
              </div>

              <p className="mt-4 text-sm text-gray-700">
                Pro helps you decide what to actually pursue — and act with confidence.
              </p>

              <div className="mt-6 space-y-6">
                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    Decision & prioritization
                  </div>
                  <div className="mt-3 space-y-3 text-sm text-gray-800">
                    <Feature>Dashboard with top matches, closing soon, average relevance</Feature>
                    <Feature>Deadline urgency indicators</Feature>
                    <Feature>Unlimited saved contracts</Feature>
                  </div>
                </div>

                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    Pipeline management
                  </div>
                  <div className="mt-3 space-y-3 text-sm text-gray-800">
                    <Feature>Pursue / Monitor / Pass pipeline statuses</Feature>
                    <Feature>Notes per opportunity</Feature>
                  </div>
                </div>

                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    Capability & positioning intelligence
                  </div>
                  <div className="mt-3 space-y-3 text-sm text-gray-800">
                    <Feature>Website extraction + manual edits + continuous sync</Feature>
                    <Feature>AI Federal Positioning Insights</Feature>
                    <Feature>Capability improvement recommendations + feedback loop</Feature>
                  </div>
                </div>

                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    Smarter alerts
                  </div>
                  <div className="mt-3 space-y-3 text-sm text-gray-800">
                    <Feature>Priority-aware daily digests + alerts</Feature>
                  </div>
                </div>
              </div>

              <div className="mt-6">
                <Link
                  href="/signup?plan=pro"
                  className="inline-flex w-full items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition"
                >
                  Get started with Pro
                </Link>
                <p className="mt-2 text-xs text-gray-500 text-center">
                  Most active bidders choose Pro to avoid chasing the wrong opportunities.
                </p>
              </div>
            </div>
          </div>

          {/* COMPARISON TABLE */}
          <div className="mt-10 bg-white rounded-xl border-2 border-gray-200 overflow-hidden">
            <div className="px-6 py-4 border-b bg-gray-50">
              <h3 className="text-lg font-bold text-gray-900">Compare plans</h3>
              <p className="text-sm text-gray-600 mt-1">
                Starter is discovery. Pro is decision-making and execution.
              </p>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-white border-b">
                  <tr className="text-left text-xs font-semibold text-gray-600 uppercase">
                    <th className="px-6 py-3">Feature</th>
                    <th className="px-6 py-3">Starter</th>
                    <th className="px-6 py-3">Pro</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  <Row feature="AI website capability matching" starter pro />
                  <Row feature="Personalized contract feed" starter pro />
                  <Row feature="Search SAM.gov" starter pro />
                  <Row feature="Save contracts" starterText="Up to 50" proText="Unlimited" />
                  <Row feature="Dashboard insights" pro />
                  <Row feature="Closing soon prioritization" pro />
                  <Row feature="Pipeline statuses + notes" pro />
                  <Row feature="Capability refinement & editing" pro />
                  <Row feature="AI positioning recommendations" pro />
                  <Row feature="Smarter alerts & digests" pro />
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-14 bg-gray-50 border-t">
        <div className="max-w-5xl mx-auto px-6">
          <div className="text-center mb-10">
            <h2 className="text-3xl font-bold text-gray-900">FAQ</h2>
            <p className="text-gray-600 mt-2">Quick answers before you start.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Faq
              q="Is this per user or per company?"
              a="Right now, each subscription is for a single user. Team features are coming later."
            />
            <Faq
              q="Can I switch plans later?"
              a="Yes. You can upgrade or downgrade at any time."
            />
            <Faq
              q="Is there a free trial?"
              a="Not at the moment. We focus on delivering real value from day one rather than time-limited trials."
            />
            <Faq
              q="Where does the data come from?"
              a="All opportunities are sourced from SAM.gov and matched using your company capabilities."
            />
            <Faq
              q="Who is BidMatch best for?"
              a="Small federal contractors, IT consultancies, and service providers who want fewer distractions and better bid decisions."
            />
          </div>

          {/* FINAL CTA */}
          <div className="mt-12 bg-white rounded-xl border-2 border-gray-200 p-8 text-center">
            <h3 className="text-2xl font-bold text-gray-900 mb-3">
              Stop chasing contracts. Start prioritizing them.
            </h3>
            <div className="mt-6 flex flex-col sm:flex-row justify-center gap-3">
              <Link
                href="/signup?plan=pro"
                className="inline-flex items-center justify-center px-8 py-4 bg-blue-600 text-white text-lg font-semibold rounded-lg hover:bg-blue-700 transition"
              >
                Get started with Pro
              </Link>
              <Link
                href="/signup?plan=starter"
                className="inline-flex items-center justify-center px-8 py-4 bg-white text-gray-700 text-lg font-semibold rounded-lg border-2 border-gray-200 hover:border-gray-300 transition"
              >
                Start with Starter
              </Link>
            </div>

            <p className="text-sm text-gray-500 mt-4">
              Or{" "}
              <Link href="/quick-start-flow" className="text-blue-600 font-semibold">
                run a free website scan
              </Link>{" "}
              to see your matches first.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

function Feature({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 shrink-0 inline-flex items-center justify-center w-5 h-5 rounded-full bg-green-50 border border-green-200">
        <Check className="w-3.5 h-3.5 text-green-700" />
      </span>
      <div>{children}</div>
    </div>
  );
}

function Row({
  feature,
  starter,
  pro,
  starterText,
  proText,
}: {
  feature: string;
  starter?: boolean;
  pro?: boolean;
  starterText?: string;
  proText?: string;
}) {
  return (
    <tr>
      <td className="px-6 py-3 text-gray-900 font-medium">{feature}</td>
      <td className="px-6 py-3 text-gray-700">
        {starterText ? starterText : starter ? "✓" : "—"}
      </td>
      <td className="px-6 py-3 text-gray-700">
        {proText ? proText : pro ? "✓" : "—"}
      </td>
    </tr>
  );
}

function Faq({ q, a }: { q: string; a: string }) {
  return (
    <div className="bg-white rounded-xl border-2 border-gray-200 p-6">
      <div className="font-semibold text-gray-900">{q}</div>
      <div className="mt-2 text-sm text-gray-600">{a}</div>
    </div>
  );
}