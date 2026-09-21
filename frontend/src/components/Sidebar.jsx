import { useState } from "react";
import {
  Avatar,
  Box,
  Button,
  Typography,
  Divider,
  IconButton,
  List,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  useTheme,
  useMediaQuery,
} from "@mui/material";
import { useLocation, useNavigate } from "react-router-dom";
import DashboardIcon from "@mui/icons-material/Dashboard";
import SettingsIcon from "@mui/icons-material/Settings";
import CategoryIcon from "@mui/icons-material/Category";
import SupportAgentOutlinedIcon from "@mui/icons-material/SupportAgentOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import DevicesOutlinedIcon from "@mui/icons-material/DevicesOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import AddCircleOutlinedIcon from "@mui/icons-material/AddCircleOutlined";
import PlayCircleOutlinedIcon from "@mui/icons-material/PlayCircleOutlined";

import { useAuth } from "../auth/AuthContext";
import logo from "../assets/assets/logo/raph-logo.png";

const SIDEBAR_COLLAPSED_KEY = "sidebarCollapsed";
const COLLAPSED_W = 74;
const EXPANDED_W = 260;

const initialsOf = (name = "") =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("") || "?";

const Sidebar = ({ onNavigate, sessionActive = false }) => {
  const theme = useTheme();
  const sb = theme.palette.sidebar;
  const location = useLocation();
  const navigate = useNavigate();

  // real auth — user, role and logout all come from the login response
  const { user, isAdmin, isSuperAdmin, logout } = useAuth();

  const isNarrow = useMediaQuery(theme.breakpoints.down("md"));

  const [stored, setStored] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  const collapsed = isNarrow || stored;
  const [confirmLogout, setConfirmLogout] = useState(false);

  const toggleCollapsed = () => {
    setStored((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      } catch {
        /* collapse state just won't persist */
      }
      return next;
    });
  };

  const goTo = (path) => (onNavigate ? onNavigate(path) : navigate(path));

  const handleLogout = () => {
    setConfirmLogout(false);
    logout();
    navigate("/login", { replace: true });
  };

  const roleLabel = user?.role
    ? user.role.charAt(0).toUpperCase() + user.role.slice(1)
    : "";

  // isAdmin is the "administrator" role alone; superadmin has to be
  // included explicitly or the highest-privilege user loses the button.
  const canAddPart = Boolean(isAdmin || isSuperAdmin);

  const menuItems = [
    { name: "Dashboard", path: "/", icon: <DashboardIcon fontSize="small" /> },
    { name: "Part Details", path: "/part-details", icon: <CategoryIcon fontSize="small" /> },
    { name: "Health Check", path: "/health-check", icon: <DevicesOutlinedIcon fontSize="small" /> },
    { name: "Device Settings", path: "/device-settings", icon: <SettingsIcon fontSize="small" /> },
  ];

  const bottomItems = [
    {
      name: "Technical Support",
      path: "/technical-support",
      icon: <SupportAgentOutlinedIcon fontSize="small" />,
    },
  ];

  const disabledSx = {
    background: sb.disabledBg,
    color: sb.disabledText,
    boxShadow: "none",
    border: "1px solid transparent",
  };

  const primaryActionSx = {
    background: theme.palette.gradients.primary,
    color: "#FFFFFF",
    borderRadius: "8px",
    boxShadow: "0 4px 12px rgba(183,28,28,0.25)",
    "&:hover": {
      background: "linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%)",
      boxShadow: "0 6px 16px rgba(183,28,28,0.32)",
    },
    "&.Mui-disabled": disabledSx,
  };

  const secondaryActionSx = {
    bgcolor: sb.surface,
    color: sb.textStrong,
    border: `1px solid ${sb.surfaceBorder}`,
    borderRadius: "8px",
    "&:hover": {
      bgcolor: "#FFFFFF",
      borderColor: sb.accent,
      color: sb.accent,
    },
    "&.Mui-disabled": disabledSx,
  };

  const NavButton = ({ item }) => {
    const active = location.pathname === item.path;
    const btn = (
      <Button
        onClick={() => goTo(item.path)}
        fullWidth
        startIcon={collapsed ? null : item.icon}
                        sx={{
                    justifyContent: collapsed ? "center" : "flex-start",
                    textTransform: "none",
                    minWidth: 0,
                    px: collapsed ? 0 : 2,
                    py: 1,
                    mb: 0.5,
                    fontWeight: active ? 600 : 500,
                    fontSize: "14px",
                    color: active ? sb.accent : sb.text,
                    bgcolor: active ? sb.activeBg : "transparent",
                    boxShadow: active ? sb.activeShadow : "none",
                    borderRadius: "8px",
                    "& .MuiSvgIcon-root": {
                      color: active ? sb.accent : sb.textMuted,
                      transition: "color 0.15s",
                    },
                    "&:hover": {
                      bgcolor: active ? sb.activeBg : sb.hover,
                      color: active ? sb.accent : sb.textStrong,
                      "& .MuiSvgIcon-root": { color: sb.accent },
                    },
                  }}
      >
        {collapsed ? item.icon : item.name}
      </Button>
    );

    return collapsed ? (
      <Tooltip title={item.name} placement="right">
        <Box>{btn}</Box>
      </Tooltip>
    ) : (
      btn
    );
  };

  const SectionLabel = ({ children }) =>
    collapsed ? null : (
      <Typography
        sx={{
          fontSize: "11px",
          fontWeight: 600,
          letterSpacing: "1.2px",
          color: sb.textMuted,
          px: 2,
          mb: 1,
        }}
      >
        {children}
      </Typography>
    );

  return (
    <Box
      sx={{
        width: { xs: "100%", md: collapsed ? COLLAPSED_W : EXPANDED_W },
        height: { xs: "auto", md: "100%" },
        flexShrink: 0,
        background: sb.background,
        color: sb.text,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        borderRight: { xs: "none", md: `1px solid ${sb.divider}` },
        borderBottom: { xs: `1px solid ${sb.divider}`, md: "none" },
        overflowY: "auto",
        overflowX: "hidden",
        transition: "width 0.2s ease",
        userSelect: "none",
      }}
    >
      {/* TOP */}
      <Box sx={{ p: collapsed ? 1 : 2 }}>
        <Box
          sx={{
            display: "flex",
            justifyContent: collapsed ? "center" : "space-between",
            alignItems: "center",
            mb: 3,
            pt: 0.5,
          }}
        >
          {!collapsed && (
            <Box
              component="img"
              src={logo}
              alt="Raph Technology Labs"
              sx={{ width: 130, height: "auto", display: "block" }}
              onError={(e) => (e.target.style.display = "none")}
            />
          )}

          {!isNarrow && (
            <Tooltip
              title={collapsed ? "Expand menu" : "Hide menu"}
              placement="right"
            >
              <IconButton
                size="small"
                onClick={toggleCollapsed}
                sx={{
                  color: sb.textMuted,
                  bgcolor: sb.surface,
                  border: `1px solid ${sb.surfaceBorder}`,
                  borderRadius: "8px",
                  "&:hover": { color: sb.accent, bgcolor: "#FFFFFF" },
                }}
              >
                {collapsed ? (
                  <ChevronRightIcon fontSize="small" />
                ) : (
                  <ChevronLeftIcon fontSize="small" />
                )}
              </IconButton>
            </Tooltip>
          )}
        </Box>

        {/* New session — primary red action */}
        {collapsed ? (
          <Tooltip
            title={
              sessionActive ? "Stop the running session first" : "New session"
            }
            placement="right"
          >
            <span>
              <IconButton
                disabled={sessionActive}
                onClick={() => goTo("/part-selection")}
                sx={{ width: "100%", mb: 1, ...primaryActionSx }}
              >
                <PlayCircleOutlinedIcon />
              </IconButton>
            </span>
          </Tooltip>
        ) : (
          <Button
            fullWidth
            disabled={sessionActive}
            onClick={() => goTo("/part-selection")}
            sx={{
              py: 1.1,
              mb: 1,
              textTransform: "none",
              fontWeight: 600,
              ...primaryActionSx,
            }}
          >
            + New Session
          </Button>
        )}

        {/* Add part — administrator and superadministrator only.
            The <span> wrappers exist so the tooltip still fires: a disabled
            MUI button emits no mouse events, so an operator would otherwise
            get a dead grey button with no reason given. */}
        {collapsed ? (
          <Tooltip
            title={
              canAddPart
                ? sessionActive
                  ? "Stop the running session first"
                  : "Add part"
                : "Administrator access required"
            }
            placement="right"
          >
            <span>
              <IconButton
                disabled={!canAddPart || sessionActive}
                onClick={() => goTo("/add-part")}
                sx={{ width: "100%", mb: 3, ...secondaryActionSx }}
              >
                <AddCircleOutlinedIcon />
              </IconButton>
            </span>
          </Tooltip>
        ) : (
          <Tooltip
            title={
              canAddPart
                ? sessionActive
                  ? "Stop the running session first"
                  : ""
                : "Administrator access required"
            }
            placement="right"
          >
            <span style={{ display: "block" }}>
              <Button
                fullWidth
                disabled={!canAddPart || sessionActive}
                onClick={() => goTo("/add-part")}
                sx={{
                  py: 1.1,
                  mb: 3,
                  textTransform: "none",
                  fontWeight: 600,
                  ...secondaryActionSx,
                }}
              >
                + Add Part
              </Button>
            </span>
          </Tooltip>
        )}

        <SectionLabel>NAVIGATION</SectionLabel>

        <List disablePadding>
          {menuItems.map((item) => (
            <NavButton key={item.path} item={item} />
          ))}
        </List>
      </Box>

      {/* BOTTOM */}
      <Box sx={{ p: collapsed ? 1 : 2, mt: "auto" }}>
        {bottomItems.map((item) => (
          <NavButton key={item.path} item={item} />
        ))}

        <Divider sx={{ my: 1.5, borderColor: sb.divider }} />

        {collapsed ? (
          <Tooltip
            title={user ? `${user.user_name} — sign out` : "Sign out"}
            placement="right"
          >
            <IconButton
              onClick={() => setConfirmLogout(true)}
              sx={{
                width: "100%",
                borderRadius: "8px",
                color: sb.textMuted,
                "&:hover": { color: sb.accent, bgcolor: sb.hover },
              }}
            >
              <LogoutOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : (
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1.25,
              p: 1,
              borderRadius: "10px",
              bgcolor: sb.surface,
              border: `1px solid ${sb.surfaceBorder}`,
            }}
          >
            <Avatar
              sx={{
                width: 34,
                height: 34,
                fontSize: "13px",
                fontWeight: 700,
                background: theme.palette.gradients.primary,
                color: "#FFFFFF",
              }}
            >
              {initialsOf(user?.user_name)}
            </Avatar>

            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography
                noWrap
                sx={{ fontSize: "13px", fontWeight: 600, color: sb.textStrong }}
              >
                {user?.user_name || "Not signed in"}
              </Typography>
              <Typography noWrap sx={{ fontSize: "11px", color: sb.textMuted }}>
                {roleLabel}
              </Typography>
            </Box>

            <Tooltip title="Sign out">
              <IconButton
                size="small"
                onClick={() => setConfirmLogout(true)}
                sx={{
                  color: sb.textMuted,
                  borderRadius: "8px",
                  "&:hover": { color: sb.accent, bgcolor: sb.hover },
                }}
              >
                <LogoutOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        )}
      </Box>

      {/* Logout confirmation */}
      <Dialog open={confirmLogout} onClose={() => setConfirmLogout(false)}>
        <DialogTitle sx={{ fontWeight: 700 }}>Sign out?</DialogTitle>
        {sessionActive && (
          <DialogContent>
            <Typography variant="body2" sx={{ color: "error.main" }}>
              An inspection session is running. Stop it before signing out.
            </Typography>
          </DialogContent>
        )}
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button
            onClick={() => setConfirmLogout(false)}
            sx={{ color: "text.secondary", textTransform: "none" }}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            color="primary"
            sx={{ textTransform: "none" }}
            onClick={handleLogout}
          >
            Sign out
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Sidebar;