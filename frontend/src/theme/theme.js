import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",

    primary: {
      main: "#b71c1c", // brand red (matches SCM) — active nav, primary actions
      light: "#d32f2f", // lighter red, matches SCM's primary.light
      dark: "#8e1414",
      contrastText: "#FFFFFF",
    },

    secondary: {
      main: "#111111", // black, matches SCM
      light: "#333333",
      dark: "#000000",
      contrastText: "#FFFFFF",
    },

    // soft peach/pink used for subtle highlights, hover states, info chips
    accent: {
      main: "#FEE2E2", // matches SCM's peach/accent.main
      light: "#FDF1EF", // matches SCM's accent.light
      dark: "#f7e582", // matches SCM's peach.dark/accent.dark
      contrastText: "#1A1A1A",
    },

    background: {
      default: "#F5F6F8", // matches SCM
      paper: "#FFFFFF",
    },

    text: {
      primary: "#1A1A1A",
      secondary: "#6A7382", // matches SCM
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
      main: "#D92D20", // matches SCM
    },

    success: {
      main: "#16A34A",
    },

    warning: {
      main: "#D97706",
    },

    divider: "#E5E7EB",

    // Custom gradient tokens — use via theme.palette.gradients.xxx in sx props
    gradients: {
      primary: "linear-gradient(135deg, #b71c1c 0%, #8e1414 100%)", // matches SCM
      dark: "linear-gradient(135deg, #1A1A1A 0%, #000000 100%)", // matches SCM
      peach: "linear-gradient(135deg, #FCE8E6 0%, #F7C8C2 100%)", // soft peach (active nav bg, highlight cards) — kept as-is, not SCM's accent.dark (that rendered as an unwanted yellow stop)
      hero: "linear-gradient(135deg, #111111 0%, #b71c1c 55%, #FEE2E2 100%)", // bold black→red→peach (login screen, banners)
      subtle: "linear-gradient(180deg, #FFFFFF 0%, #F5F6F8 100%)", // barely-there page/card gradient
    },
  },

  typography: {
    fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif", // matches SCM

    h1: {
      fontSize: "2rem",
      fontWeight: 700,
      color: "#1A1A1A",
    },

    h2: {
      fontSize: "1.5rem",
      fontWeight: 600,
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
    borderRadius: 6, // matches SCM
  },

  components: {
    // matches SCM: hides the text caret app-wide except real text inputs
    MuiCssBaseline: {
      styleOverrides: {
        img: { userSelect: "none", WebkitUserDrag: "none" },
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
        },
        containedSecondary: {
          backgroundImage: "linear-gradient(135deg, #1A1A1A 0%, #000000 100%)",
          "&:hover": {
            backgroundImage: "linear-gradient(135deg, #333333 0%, #111111 100%)",
          },
        },
      },
    },

    // red focus border on every TextField, matches SCM
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: "#b71c1c",
          },
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
