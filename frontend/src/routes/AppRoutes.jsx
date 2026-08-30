import { Routes, Route } from "react-router-dom";
import DashboardPage from "../pages/DashboardPage";
import PlaceholderPage from "../pages/PlaceholderPage";
import InspectionPage from "../pages/InspectionPage";
import PartSelectionPage from "../pages/PartSelectionPage";
import DeviceSettingsPage from "../pages/DeviceSettingsPage";
import HealthCheckPage from "../pages/HealthCheckPage";
import TechnicalSupport from "../pages/TechinicalSupport";

const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/inspection" element={<InspectionPage />} />
      <Route path="/add-part" element={<PlaceholderPage title="Add New Part" />} />
      <Route path="/part-details" element={<PlaceholderPage title="Part Details" />} />
      <Route path="/part-selection" element={<PartSelectionPage />} />
      <Route path="/counting/:sessionId" element={<PlaceholderPage title="Counting" />} />
      <Route path="/health-check" element={<HealthCheckPage />} />
      <Route path="/batching" element={<PlaceholderPage title="Batching Mode" />} />
      <Route path="/batching/:sessionId" element={<PlaceholderPage title="Batching Mode" />} />
      <Route path="/device-settings" element={<DeviceSettingsPage />} />
      <Route path="/technical-support" element={<TechnicalSupport />} />

      <Route path="*" element={<PlaceholderPage title="404 — Not Found" />} />
    </Routes>
  );

};

export default AppRoutes;