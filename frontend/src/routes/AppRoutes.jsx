import { Routes, Route, Navigate } from "react-router-dom";

import RequireAuth from "../components/RequireAuth";
import MainLayout from "../layouts/MainLayout";

import LoginPage from "../pages/LoginPage";
import DashboardPage from "../pages/DashboardPage";
import PartSelectionPage from "../pages/PartSelectionPage";
import InspectionPage from "../pages/InspectionPage";
import HealthCheckPage from "../pages/HealthCheckPage";
import DeviceSettingsPage from "../pages/DeviceSettingsPage";
import TechnicalSupport from "../pages/TechinicalSupport";
import PlaceholderPage from "../pages/PlaceholderPage";

const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      {/* everything below renders inside MainLayout, which mounts once */}
      <Route
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/part-selection" element={<PartSelectionPage />} />
        <Route path="/inspection" element={<InspectionPage />} />
        <Route path="/part-details" element={<PlaceholderPage title="Part Details" />} />
        <Route path="/add-part" element={<PlaceholderPage title="Add New Part" />} />
        <Route path="/health-check" element={<HealthCheckPage />} />
        <Route path="/device-settings" element={<DeviceSettingsPage />} />
        <Route path="/technical-support" element={<TechnicalSupport />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default AppRoutes;