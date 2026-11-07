import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";

export function NotFoundPage() {
  return (
    <>
      <PageHeader
        eyebrow="404"
        title="That page is not in this pool."
        lead="The link may be old, or the page moved. The dashboard and operator console are the two places that matter."
      />
      <div className="row">
        <Link className="btn btn--primary" to="/">
          Back to the dashboard
        </Link>
        <Link className="btn btn--secondary" to="/operator">
          Operator console
        </Link>
      </div>
    </>
  );
}
