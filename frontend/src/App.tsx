import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { DashboardPage } from "./pages/Dashboard";
import { EnrollPage } from "./pages/Enroll";
import { FundPage } from "./pages/Fund";
import { LimitsPage } from "./pages/Limits";
import { NotFoundPage } from "./pages/NotFound";
import { OperatorPage } from "./pages/Operator";
import { ReceiptsPage } from "./pages/Receipts";

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/enroll" element={<EnrollPage />} />
            <Route path="/fund" element={<FundPage />} />
            <Route path="/operator" element={<OperatorPage />} />
            <Route path="/receipts" element={<ReceiptsPage />} />
            <Route path="/limits" element={<LimitsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Layout>
      </ToastProvider>
    </BrowserRouter>
  );
}
