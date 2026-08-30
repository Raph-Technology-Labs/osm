import { Routes, Route } from "react-router-dom";
import DashboardPage from "../pages/DashboardPage";
import PlaceholderPage from "../pages/PlaceholderPage";
import ModeSelectionPage from "../pages/ModeSelectionPage";
import InspectionPage from "../pages/InspectionPage";

const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/inspection" element={<InspectionPage />} />
      <Route path="/add-part" element={<PlaceholderPage title="Add New Part" />} />
      <Route path="/part-details" element={<PlaceholderPage title="Part Details" />} />
      <Route path="/part-selection" element={<PlaceholderPage title="Part Selection" />} />
      <Route path="/counting/:sessionId" element={<PlaceholderPage title="Counting" />} />
      <Route path="/health-check" element={<PlaceholderPage title="Health Check" />} />
      <Route path="/batching" element={<PlaceholderPage title="Batching Mode" />} />
      <Route path="/batching/:sessionId" element={<PlaceholderPage title="Batching Mode" />} />
      <Route path="/mode-selection" element={<ModeSelectionPage />} />
      <Route path="/device-settings" element={<PlaceholderPage title="Device Settings" />} />
      <Route path="/technical-support" element={<PlaceholderPage title="Technical Support" />} />

      <Route path="*" element={<PlaceholderPage title="404 — Not Found" />} />
    </Routes>
  );
};

export default AppRoutes;