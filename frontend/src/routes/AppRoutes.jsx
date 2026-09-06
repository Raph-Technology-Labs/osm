import { Routes, Route } from "react-router-dom";
import DashboardPage from "../pages/DashboardPage";
import PlaceholderPage from "../pages/PlaceholderPage";
import InspectionPage from "../pages/InspectionPage";
import PartSelectionPage from "../pages/PartSelectionPage";
import DeviceSettingsPage from "../pages/DeviceSettingsPage";
import HealthCheckPage from "../pages/HealthCheckPage";
import TechnicalSupport from "../pages/TechinicalSupport";
import LoginPage from "../pages/LoginPage";
import SignOutPage from "../pages/SignOutPage";
import RequireAuth from "../components/RequireAuth";

const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signout" element={<SignOutPage />} />

      <Route path="/" element={<RequireAuth><DashboardPage /></RequireAuth>} />
      <Route path="/inspection" element={<RequireAuth><InspectionPage /></RequireAuth>} />
      <Route path="/add-part" element={<RequireAuth><PlaceholderPage title="Add New Part" /></RequireAuth>} />
      <Route path="/part-details" element={<RequireAuth><PlaceholderPage title="Part Details" /></RequireAuth>} />
      <Route path="/part-selection" element={<RequireAuth><PartSelectionPage /></RequireAuth>} />
      <Route path="/counting/:sessionId" element={<RequireAuth><PlaceholderPage title="Counting" /></RequireAuth>} />
      <Route path="/health-check" element={<RequireAuth><HealthCheckPage /></RequireAuth>} />
      <Route path="/batching" element={<RequireAuth><PlaceholderPage title="Batching Mode" /></RequireAuth>} />
      <Route path="/batching/:sessionId" element={<RequireAuth><PlaceholderPage title="Batching Mode" /></RequireAuth>} />
      <Route path="/device-settings" element={<RequireAuth><DeviceSettingsPage /></RequireAuth>} />
      <Route path="/technical-support" element={<RequireAuth><TechnicalSupport /></RequireAuth>} />

      <Route path="*" element={<PlaceholderPage title="404 — Not Found" />} />
    </Routes>
  );

};

export default AppRoutes;