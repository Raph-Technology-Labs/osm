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

  // Shared styles for the bigger inputs
  const labelSx = {
    fontSize: "14px",
    fontWeight: 700,
    color: theme.palette.text.primary,
    mb: 0.8,
  };

  const inputSx = {
    "& .MuiInputBase-input": { fontSize: "16px", py: 1.6 },
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
          justifyContent: "flex-end",
          position: "relative",
          overflow: "hidden",
          p: { sm: 4, md: 6 },
          background: theme.palette.gradients.hero,
        }}
      >
        {/* Product information */}
        <Box sx={{ position: "relative", zIndex: 2, my: "auto" }}>
          <Typography
            variant="h1"
            sx={{
              color: theme.palette.login.heroText,
              fontSize: { sm: "46px", md: "60px" },
              fontWeight: 700,
              lineHeight: 1.05,
              letterSpacing: "-1.5px",
              maxWidth: "600px",
            }}
          >
            Optical Sorting
            <br />
            Machine
          </Typography>

          <Typography
            sx={{
              color: theme.palette.login.heroText,
              fontSize: { sm: "18px", md: "21px" },
              mt: 2.5,
              fontWeight: 400,
            }}
          >
            Vision inspection and reject control
          </Typography>
        </Box>

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
          position: "relative",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: theme.palette.background.default,
          p: { xs: 2, sm: 3, md: 5 },
        }}
      >
        {/* Logo */}
        <Box
          component="img"
          src={raphLogo}
          alt="Raph Technology Labs"
          sx={{
            position: "absolute",
            top: 24,
            right: 24,
            height: 90,
            width: "auto",
          }}
        />

        <Paper
          elevation={0}
          sx={{
            width: "100%",
            maxWidth: 480,
            p: { xs: 3.5, sm: 5 },
            borderRadius: "12px",
            border: `1px solid ${theme.palette.divider}`,
            backgroundColor: theme.palette.background.paper,
            boxShadow: "0 16px 40px rgba(17,17,17,.08)",
          }}
        >
          <Box sx={{ mb: 3.5 }}>
            <Typography
              variant="h2"
              sx={{
                fontSize: "30px",
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
                fontSize: "15px",
                color: theme.palette.text.secondary,
                mt: 1,
              }}
            >
              Use your operator or admin account
            </Typography>
          </Box>

          {error && (
            <Alert severity="error" sx={{ mb: 2.5, fontSize: "14px" }}>
              {error}
            </Alert>
          )}

          <Box
            component="form"
            onSubmit={handleSubmit}
            sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}
          >
            <Box>
              <Typography sx={labelSx}>Username</Typography>

              <TextField
                fullWidth
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="operator01"
                autoFocus
                required
                disabled={loading}
                sx={inputSx}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <PersonOutlineIcon />
                    </InputAdornment>
                  ),
                }}
              />
            </Box>

            <Box>
              <Typography sx={labelSx}>Password</Typography>

              <TextField
                fullWidth
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
                sx={inputSx}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <LockOutlinedIcon />
                    </InputAdornment>
                  ),
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton
                        type="button"
                        onClick={() => setShowPassword((s) => !s)}
                        edge="end"
                        aria-label={
                          showPassword ? "Hide password" : "Show password"
                        }
                      >
                        {showPassword ? <VisibilityOff /> : <Visibility />}
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
                mt: 1,
                height: 54,
                fontSize: "17px",
                fontWeight: 600,
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