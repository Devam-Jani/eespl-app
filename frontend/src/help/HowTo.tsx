// "How to" at the top of each page: that page's section in the person's role SOP (help/Sop.tsx).
import { Link, matchPath, useLocation } from "react-router-dom";
import { MENU } from "../menu";
import { DETAIL_ROUTES } from "../routes";

/** The route pattern of a path: the menu page it is, else the detail page it matches. */
export function routeKey(path: string): string | null {
  if (MENU.some((i) => i.to === path)) return path;
  return DETAIL_ROUTES.find((r) => matchPath(r.path, path))?.path ?? null;
}

/** "How to", next to the "?": this page's section of the person's role SOP. */
export function HowToLink({ base = "/help/sop" }: { base?: string }) {
  const location = useLocation();
  const key = routeKey(location.pathname);
  if (!key || location.pathname.startsWith(base)) return null;
  return (
    <Link className="howto-link" to={`${base}?page=${encodeURIComponent(key)}`} title="How to: this page in your role's SOP">
      How to
    </Link>
  );
}
