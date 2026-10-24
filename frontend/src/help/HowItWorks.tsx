// "How the app works" (EESPL UI v1, Figma 04): the ten steps from the first lead to the guarantee,
// with the role that does each; a box opens its page for the roles that may open it, the others
// read it as a picture of the flow.
import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import { MENU, type MenuItem } from "../menu";

type Step = { n: number; title: string; who: string; to: string[]; highlight?: "accent" | "done" };

// each step's page: the first of these the role may open
export const STEPS: Step[] = [
  { n: 1, title: "Lead and site visit", who: "Sales", to: ["/leads"] },
  { n: 2, title: "Quotation", who: "Sales, estimator", to: ["/quotations"] },
  { n: 3, title: "Tender and BOQ", who: "Estimator, from the rate library", to: ["/tenders"] },
  { n: 4, title: "Work order", who: "Billing locks units and rates", to: ["/work-orders", "/sales/work-orders"] },
  { n: 5, title: "Site, stages and 3D", who: "Planning, from the drawing", to: ["/sites"], highlight: "accent" },
  { n: 6, title: "Daily work", who: "Site engineer: reports, materials", to: ["/daily-reports"] },
  { n: 7, title: "Measurement", who: "Billing; client approves", to: ["/measurements"] },
  { n: 8, title: "RA bill", who: "Billing, accounts", to: ["/bills", "/sales/bills"] },
  { n: 9, title: "Payment", who: "Accounts, with follow-ups", to: ["/billing/payments", "/sales/bills"] },
  { n: 10, title: "Certificate and guarantee", who: "Billing, director signs", to: ["/guarantees"], highlight: "done" },
];

export const SHARED: { title: string; to: string[] }[] = [
  { title: "Rate library and products", to: ["/rate-library", "/products"] },
  { title: "Users and roles", to: ["/admin/users"] },
  { title: "Stores: indent, PO, GRN", to: ["/indents"] },
  { title: "Client portal", to: ["/settings/client-roles"] },
  { title: "Issue log and helper", to: ["/settings/issue-log", "/my-reports"] },
];

function mayOpen(item: MenuItem, can: (...p: string[]) => boolean): boolean {
  return can(...(item.view ?? item.perms)) && (!item.all || can(...item.all)) && (!item.none || !can(...item.none));
}

/** The page a step opens for this role (null: the role does not open it). */
export function pageFor(paths: string[], can: (...p: string[]) => boolean): string | null {
  for (const p of paths) {
    const item = MENU.find((i) => i.to === p);
    if (!item) continue;
    if (mayOpen(item, can)) return p;
  }
  return null;
}

function Box({ step, can }: { step: Step; can: (...p: string[]) => boolean }) {
  const to = pageFor(step.to, can);
  const inner = (
    <>
      <b>
        {step.n}. {step.title}
      </b>
      <span>{step.who}</span>
    </>
  );
  const cls = `flow-box ${step.highlight ? `flow-${step.highlight}` : ""}`;
  return to ? (
    <Link to={to} className={cls} aria-label={`Step ${step.n}, ${step.title} (${step.who}): open`}>
      {inner}
    </Link>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

export default function HowItWorks() {
  const { can } = useAuth();
  const row1 = STEPS.slice(0, 5);
  const row2 = STEPS.slice(5).reverse(); // 10 ← 9 ← 8 ← 7 ← 6, as the design reads
  return (
    <div className="flow">
      <h1>How the app works: from the first lead to the guarantee</h1>
      <p className="muted">Each box is one step, with the role that does it. Data moves along the arrows; nobody types it twice.</p>
      <ol className="flow-row" aria-label="Steps 1 to 5">
        {row1.map((s, i) => (
          <li key={s.n}>
            <Box step={s} can={can} />
            {i < row1.length - 1 && (
              <span className="flow-arrow" aria-hidden="true">
                →
              </span>
            )}
          </li>
        ))}
      </ol>
      <div className="flow-down" aria-hidden="true">
        ↓
      </div>
      <ol className="flow-row" aria-label="Steps 6 to 10">
        {row2.map((s, i) => (
          <li key={s.n}>
            <Box step={s} can={can} />
            {i < row2.length - 1 && (
              <span className="flow-arrow" aria-hidden="true">
                ←
              </span>
            )}
          </li>
        ))}
      </ol>
      <section className="flow-shared" aria-label="Shared by every step">
        <p>Shared by every step</p>
        <ul>
          {SHARED.map((s) => {
            const to = pageFor(s.to, can);
            return <li key={s.title}>{to ? <Link to={to}>{s.title}</Link> : <span>{s.title}</span>}</li>;
          })}
        </ul>
      </section>
    </div>
  );
}
