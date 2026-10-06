import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import { MENU } from "../menu";

export default function Home() {
  const { me, can } = useAuth();
  const modules = MENU.filter((m) => can(...m.perms));
  return (
    <>
      <h1>Welcome, {me?.user.full_name.split(" ")[0]}</h1>
      {modules.length === 0 ? (
        <p className="muted">Your account has no modules yet. Ask an administrator to assign a role.</p>
      ) : (
        <div className="tiles">
          {modules.map((m) => (
            <Link key={m.to} to={m.to} className="tile">
              <span className="tile-title">{m.label}</span>
              <span className="muted">{m.section}</span>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
