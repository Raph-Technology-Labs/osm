import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",

    primary: {
      main: "#b71c1c", // brand red — active nav, primary actions
      light: "#d32f2f",
      dark: "#8e1414",
      contrastText: "#FFFFFF",
    },

    secondary: {
      main: "#111111",
      light: "#333333",
      dark: "#000000",
      contrastText: "#FFFFFF",
    },

    // soft peach/pink used for subtle highlights, hover states, info chips
    accent: {
      main: "#FEE2E2",
      light: "#FDF1EF",
      dark: "#F7C8C2",
      contrastText: "#1A1A1A",
    },

    background: {
      default: "#F5F6F8",
      paper: "#FFFFFF",
    },

    text: {
      primary: "#1A1A1A",
      secondary: "#6A7382",
    },

    grey: {
      50: "#F9FAFB",
      100: "#F3F4F6",
      200: "#E5E7EB",
      300: "#D1D5DB",
      400: "#9CA3AF",
      500: "#6B7280",
      600: "#4B5563",
      700: "#374151",
      800: "#1F2937",
      900: "#111111",
    },

    error: {
      main: "#D92D20",
      light: "#FEE2E2",
      dark: "#8A2019",
      contrastText: "#FFFFFF",
    },

    success: {
      main: "#16A34A",
      light: "#DCFCE7",
      dark: "#15803D",
      contrastText: "#FFFFFF",
    },

    warning: {
      main: "#D97706",
      light: "#FFFBEB",
      dark: "#7A5A0A",
      contrastText: "#FFFFFF",
    },

    divider: "#E5E7EB",

    // Custom gradient tokens — use via theme.palette.gradients.xxx in sx props
    gradients: {
      primary: "linear-gradient(135deg, #b71c1c 0%, #8e1414 100%)",
      dark: "linear-gradient(135deg, #1A1A1A 0%, #000000 100%)",
      peach: "linear-gradient(135deg, #FCE8E6 0%, #F7C8C2 100%)", // active nav bg, highlight cards
      hero: "linear-gradient(135deg, #111111 0%, #b71c1c 55%, #FEE2E2 100%)", // login screen, banners
      subtle: "linear-gradient(180deg, #FFFFFF 0%, #F5F6F8 100%)",
    },

    // Login / hero panel tokens — referenced by LoginPage
    login: {
      outerBackground: "#E8EAEE",

      heroText: "#FFFFFF",
      heroSubText: "rgba(255,255,255,0.90)",
      heroMutedText: "rgba(255,255,255,0.85)",

      heroCircle: "rgba(255,255,255,0.16)",
      heroCircleBorder: "rgba(255,255,255,0.25)",
      heroDot: "rgba(255,255,255,0.45)",
    },
  },

  typography: {
    fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",

    h1: {
      fontSize: "2rem",
      fontWeight: 700,
      color: "#1A1A1A",
      letterSpacing: "-1px",
    },

    h2: {
      fontSize: "1.5rem",
      fontWeight: 600,
      color: "#1A1A1A",
      letterSpacing: "-0.3px",
    },

    h5: {
      fontSize: "0.75rem",
      fontWeight: 700,
      color: "#1A1A1A",
    },

    h6: {
      fontWeight: 600,
      color: "#1A1A1A",
    },

    body1: {
      fontSize: "1rem",
    },

    body2: {
      color: "#6A7382",
    },

    button: {
      textTransform: "none",
      fontWeight: 600,
    },
  },

  shape: {
    borderRadius: 6,
  },

  components: {
    MuiCssBaseline: {
      styleOverrides: {
        // lets height:100% work anywhere below the root
        "html, body, #root": {
          height: "100%",
          width: "100%",
          margin: 0,
        },
        img: { userSelect: "none", WebkitUserDrag: "none" },
        // hides the text caret app-wide except in real text inputs
        "*": { caretColor: "transparent" },
        "input, textarea": { caretColor: "auto" },
      },
    },

    // Buttons use gradients instead of flat fills
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 5,
        },
        containedPrimary: {
          backgroundImage: "linear-gradient(135deg, #b71c1c 0%, #8e1414 100%)",
          "&:hover": {
            backgroundImage: "linear-gradient(135deg, #8e1414 0%, #6b0f0f 100%)",
          },
          "&:disabled": {
            backgroundImage: "none",
            backgroundColor: "#F3F4F6",
            color: "#9CA3AF",
          },
        },
        containedSecondary: {
          backgroundImage: "linear-gradient(135deg, #1A1A1A 0%, #000000 100%)",
          "&:hover": {
            backgroundImage: "linear-gradient(135deg, #333333 0%, #111111 100%)",
          },
        },
      },
    },

    // red focus border on every TextField
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: "#b71c1c",
          },
        },
      },
    },

    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 5,
          fontSize: "12px",
        },
        standardError: {
          backgroundColor: "#FEE2E2",
          color: "#D92D20",
          border: "1px solid #F4B4B0",
        },
        standardWarning: {
          backgroundColor: "#FFFBEB",
          color: "#5C4409",
          border: "1px solid #FCD9A6",
        },
        standardSuccess: {
          backgroundColor: "#DCFCE7",
          color: "#15803D",
        },
      },
    },

    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 6,
        },
      },
    },

    MuiTableHead: {
      styleOverrides: {
        root: {
          backgroundColor: "#F5F5F5",
        },
      },
    },

    MuiTableCell: {
      styleOverrides: {
        head: {
          fontWeight: "bold",
          color: "#111827",
        },
      },
    },

    MuiTableRow: {
      styleOverrides: {
        root: {
          "&:hover": {
            backgroundColor: "#FDF1EF",
          },
        },
      },
    },

    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: "#FFFFFF",
          borderRight: "1px solid #E5E7EB",
        },
      },
    },

    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: "#E5E7EB",
        },
      },
    },
  },
});

export default theme;