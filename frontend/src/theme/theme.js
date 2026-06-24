import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",

    primary: {
      main: "#D92D20", // brand red — active nav, primary actions
      light: "#FCE8E6", // soft peach-pink — active nav / hover background
      dark: "#A8221A",
      contrastText: "#FFFFFF",
    },

    secondary: {
      main: "#1A1A1A", // near-black — buttons, headings
      light: "#333333",
      dark: "#000000",
      contrastText: "#FFFFFF",
    },

    // soft peach/pink used for subtle highlights, hover states, info chips
    accent: {
      main: "#F7C8C2", // light peach-pink
      light: "#FDF1EF", // barely-there blush, good for card/row hover
      dark: "#E8A39B",
      contrastText: "#1A1A1A",
    },

    background: {
      default: "#FAF8F7", // warm-neutral page background (hint of peach, not grey)
      paper: "#FFFFFF", // cards, sidebar, tables
    },

    text: {
      primary: "#1A1A1A",
      secondary: "#6B7280",
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
      primary: "linear-gradient(135deg, #D92D20 0%, #A8221A 100%)", // red → deep red (CTA buttons)
      dark: "linear-gradient(135deg, #1A1A1A 0%, #000000 100%)", // black → deeper black (sidebar header / nav buttons)
      peach: "linear-gradient(135deg, #FCE8E6 0%, #F7C8C2 100%)", // soft peach (active nav bg, highlight cards)
      hero: "linear-gradient(135deg, #1A1A1A 0%, #D92D20 55%, #FCE8E6 100%)", // bold black→red→peach (login screen, banners)
      subtle: "linear-gradient(180deg, #FFFFFF 0%, #FAF8F7 100%)", // barely-there page/card gradient
    },
  },

  typography: {
    fontFamily: "'Poppins', 'Roboto', sans-serif",

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
      color: "#6B7280",
    },

    button: {
      textTransform: "none",
      fontWeight: 600,
    },
  },

  shape: {
    borderRadius: 8,
  },

  components: {
    // Buttons now use gradients instead of flat fills
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 5,
        },
        containedPrimary: {
          backgroundImage: "linear-gradient(135deg, #D92D20 0%, #A8221A 100%)",
          "&:hover": {
            backgroundImage: "linear-gradient(135deg, #A8221A 0%, #7A1812 100%)",
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

    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 8,
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