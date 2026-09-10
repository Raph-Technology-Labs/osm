import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Paper,
  TextField,
  Button,
  Typography,
  Alert,
  InputAdornment,
  IconButton,
} from "@mui/material";
import PersonOutlineIcon from "@mui/icons-material/PersonOutline";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import Visibility from "@mui/icons-material/Visibility";
import VisibilityOff from "@mui/icons-material/VisibilityOff";
import { useTheme } from "@mui/material/styles";

import api from "../api/axios";
import { useAuth } from "../auth/AuthContext";
import raphLogo from "../assets/assets/logo/raph-logo.png";

const LoginPage = () => {
  const theme = useTheme();
  const navigate = useNavigate();
  const { login } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const { data } = await api.post("/auth/login", { username, password });

      // Sidebar reads user_name and role — this is where that shape is set.
      login({
        token: data.token,
        user_id: data.user_id,
        user_name: data.name,
        role: data.role,
      });

      navigate("/", { replace: true });
    } catch (err) {
      console.error(
        "login error:",
        err.response?.status,
        err.response?.data,
        err.message
      );

      if (err.response) {
        setError(
          err.response.status === 401
            ? "Username or password is incorrect."
            : err.response.data?.detail ||
                `Server returned ${err.response.status}`
        );
      } else {
        setError("Could not reach the server.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        width: "100%",
        display: "flex",
        overflow: "hidden",
        backgroundColor: theme.palette.background.default,
      }}
    >
      {/* ---------------- LEFT HERO PANEL ---------------- */}
      <Box
        sx={{
          width: { xs: "0%", sm: "48%", md: "52%" },
          display: { xs: "none", sm: "flex" },
          flexDirection: "column",
          justifyContent: "space-between",
          position: "relative",
          overflow: "hidden",
          p: { sm: 4, md: 6 },
          background: theme.palette.gradients.hero,
        }}
      >
        {/* Logo */}
        <Box
          sx={{
            position: "relative",
            zIndex: 2,
            backgroundColor: theme.palette.background.paper,
            borderRadius: "10px",
            p: 1.5,
            width: "fit-content",
            display: "flex",
            alignItems: "center",
          }}
        >
          <Box
            component="img"
            src={raphLogo}
            alt="Raph Technology Labs"
            sx={{ height: 56, width: "auto", display: "block" }}
          />
        </Box>

        {/* Product information */}
        <Box sx={{ position: "relative", zIndex: 2, mb: 5 }}>
          <Typography
            variant="h1"
            sx={{
              color: theme.palette.login.heroText,
              fontSize: { sm: "34px", md: "42px" },
              fontWeight: 700,
              lineHeight: 1.05,
              letterSpacing: "-1px",
              maxWidth: "420px",
            }}
          >
            Optical Sorting
            <br />
            Machine
          </Typography>

          <Typography
            sx={{
              color: theme.palette.login.heroText,
              fontSize: "15px",
              mt: 2,
              fontWeight: 400,
            }}
          >
            Vision inspection and reject control
          </Typography>
        </Box>

        {/* Terminal / version */}
        <Typography
          sx={{
            position: "relative",
            zIndex: 2,
            color: theme.palette.login.heroMutedText,
            fontSize: "11px",
          }}
        >
          Line 3 · Terminal OSM-02 · v2.4.0
        </Typography>

        {/* Decorative rings */}
        <Box
          sx={{
            position: "absolute",
            width: 430,
            height: 430,
            borderRadius: "50%",
            border: `18px solid ${theme.palette.login.heroCircle}`,
            right: -110,
            bottom: -125,
          }}
        />
        <Box
          sx={{
            position: "absolute",
            width: 330,
            height: 330,
            borderRadius: "50%",
            border: `1px solid ${theme.palette.login.heroCircleBorder}`,
            right: -60,
            bottom: -75,
          }}
        />
        <Box
          sx={{
            position: "absolute",
            width: 220,
            height: 220,
            borderRadius: "50%",
            border: `1px solid ${theme.palette.login.heroCircleBorder}`,
            right: -5,
            bottom: -20,
          }}
        />

        {/* Slot dots */}
        <Box
          sx={{
            position: "absolute",
            width: 16,
            height: 16,
            borderRadius: "50%",
            backgroundColor: theme.palette.login.heroDot,
            right: 110,
            bottom: 310,
          }}
        />
        <Box
          sx={{
            position: "absolute",
            width: 16,
            height: 16,
            borderRadius: "50%",
            backgroundColor: theme.palette.login.heroDot,
            right: 305,
            bottom: 240,
          }}
        />
        <Box
          sx={{
            position: "absolute",
            width: 16,
            height: 16,
            borderRadius: "50%",
            backgroundColor: theme.palette.login.heroDot,
            right: 333,
            bottom: 110,
          }}
        />
      </Box>

      {/* ---------------- RIGHT LOGIN SECTION ---------------- */}
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: theme.palette.background.default,
          p: { xs: 2, sm: 3, md: 5 },
        }}
      >
        <Paper
          elevation={0}
          sx={{
            width: "100%",
            maxWidth: 372,
            p: { xs: 3, sm: 3.5 },
            borderRadius: "8px",
            border: `1px solid ${theme.palette.divider}`,
            backgroundColor: theme.palette.background.paper,
            boxShadow: "0 16px 40px rgba(17,17,17,.08)",
          }}
        >
          <Box sx={{ mb: 2.5 }}>
            <Typography
              variant="h2"
              sx={{
                fontSize: "21px",
                fontWeight: 700,
                color: theme.palette.text.primary,
                lineHeight: 1.2,
              }}
            >
              Sign in
            </Typography>

            <Typography
              variant="body2"
              sx={{
                fontSize: "12px",
                color: theme.palette.text.secondary,
                mt: 0.6,
              }}
            >
              Use your operator or admin account
            </Typography>
          </Box>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          <Box
            component="form"
            onSubmit={handleSubmit}
            sx={{ display: "flex", flexDirection: "column", gap: 1.7 }}
          >
            <Box>
              <Typography
                sx={{
                  fontSize: "11px",
                  fontWeight: 700,
                  color: theme.palette.text.primary,
                  mb: 0.65,
                }}
              >
                Username
              </Typography>

              <TextField
                fullWidth
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="operator01"
                autoFocus
                required
                disabled={loading}
                size="small"
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <PersonOutlineIcon fontSize="small" />
                    </InputAdornment>
                  ),
                }}
              />
            </Box>

            <Box>
              <Typography
                sx={{
                  fontSize: "11px",
                  fontWeight: 700,
                  color: theme.palette.text.primary,
                  mb: 0.65,
                }}
              >
                Password
              </Typography>

              <TextField
                fullWidth
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
                size="small"
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <LockOutlinedIcon fontSize="small" />
                    </InputAdornment>
                  ),
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton
                        type="button"
                        onClick={() => setShowPassword((s) => !s)}
                        edge="end"
                        size="small"
                        aria-label={
                          showPassword ? "Hide password" : "Show password"
                        }
                      >
                        {showPassword ? (
                          <VisibilityOff fontSize="small" />
                        ) : (
                          <Visibility fontSize="small" />
                        )}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />
            </Box>

            <Button
              type="submit"
              fullWidth
              variant="contained"
              disabled={loading}
              sx={{
                mt: 0.8,
                height: 42,
                background: theme.palette.gradients.primary,
                color: theme.palette.primary.contrastText,
                "&:hover": { background: theme.palette.gradients.dark },
              }}
            >
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </Box>
        </Paper>
      </Box>
    </Box>
  );
};

export default LoginPage;