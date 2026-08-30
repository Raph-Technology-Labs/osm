import { Box, Typography, Paper, Stack } from "@mui/material";
import EmailIcon from "@mui/icons-material/Email";
import PhoneIcon from "@mui/icons-material/Phone";
import LocationOnIcon from "@mui/icons-material/LocationOn";
import AccessTimeIcon from "@mui/icons-material/AccessTime";

import MainLayout from "../layouts/MainLayout";

const CONTACT_CARDS = [
  {
    Icon: EmailIcon,
    title: "Email",
    info: [{ text: "info@raphtechnologies.com", href: "mailto:info@raphtechnologies.com" }],
  },
  {
    Icon: PhoneIcon,
    title: "Phone",
    info: [
      { text: "+91 63812 08064", href: "tel:+916381208064" },
      { text: "+91 62390 91255", href: "tel:+916239091255" },
    ],
  },
  {
    Icon: LocationOnIcon,
    title: "Address",
    info: [
      {
        text: "Symphony IT Park, Nanded City, Pune, India",
        href: "https://www.google.com/maps/search/?api=1&query=Symphony+IT+Park+Nanded+City+Pune+India",
        multiline: ["Symphony IT Park,", "Nanded City, Pune,", "India"],
      },
    ],
  },
  {
    Icon: AccessTimeIcon,
    title: "Office Hours",
    info: [
      { text: "Mon - Fri: 9:00 AM - 6:30 PM" },
      { text: "Saturday: By Appointment" },
      { text: "Sunday: Closed" },
    ],
  },
];

const TechnicalSupport = () => {
  return (
    <MainLayout title="Technical Support">
      <Box sx={{ maxWidth: 1200, mx: "auto" }}>
        <Typography variant="body2" sx={{ color: "text.secondary", mb: 3 }}>
          Reach out to our team through any of the channels below.
        </Typography>

        <Typography
          variant="subtitle1"
          sx={{
            fontWeight: 700,
            color: "text.primary",
            mb: { xs: 1.5, sm: 2 },
          }}
        >
          Contact Information
        </Typography>

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              sm: "repeat(2, 1fr)",
              lg: "repeat(4, 1fr)",
            },
            gap: { xs: 1.5, sm: 2 },
          }}
        >
          {CONTACT_CARDS.map(({ Icon, title, info }) => (
            <Paper
              key={title}
              elevation={0}
              sx={{
                p: { xs: 2, sm: 2.5, md: 3 },
                borderRadius: 2,
                border: 1,
                borderColor: "divider",
                bgcolor: "background.paper",
                display: "flex",
                flexDirection: "column",
                gap: { xs: 1, sm: 1.5 },
                transition: "box-shadow 0.2s ease, border-color 0.2s ease",
                "&:hover": {
                  boxShadow: "0 6px 18px rgba(0,0,0,0.08)",
                  borderColor: "primary.main",
                },
              }}
            >
              <Stack direction="row" alignItems="center" spacing={1.5}>
                <Box
                  sx={{
                    width: 44,
                    height: 44,
                    flexShrink: 0,
                    borderRadius: 1.5,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    bgcolor: "accent.light",
                    color: "primary.main",
                  }}
                >
                  <Icon sx={{ fontSize: { xs: 22, sm: 24, md: 26 } }} />
                </Box>
                <Typography
                  variant="subtitle1"
                  sx={{
                    fontWeight: 700,
                    color: "text.primary",
                    fontSize: { xs: "0.9rem", sm: "1rem" },
                  }}
                >
                  {title}
                </Typography>
              </Stack>

              <Box>
                {info.map((line, i) => {
                  const textSx = {
                    color: "text.secondary",
                    lineHeight: 1.7,
                    fontSize: { xs: "0.8rem", sm: "0.875rem" },
                  };
                  const displayLines = line.multiline ?? [line.text];

                  if (!line.href) {
                    return (
                      <Typography key={i} variant="body2" sx={textSx}>
                        {line.text}
                      </Typography>
                    );
                  }

                  return (
                    <Typography
                      key={i}
                      component="a"
                      href={line.href}
                      target={line.href.startsWith("http") ? "_blank" : undefined}
                      rel={line.href.startsWith("http") ? "noopener noreferrer" : undefined}
                      variant="body2"
                      sx={{
                        ...textSx,
                        display: "block",
                        color: "primary.main",
                        textDecoration: "none",
                        "&:hover": { textDecoration: "underline" },
                      }}
                    >
                      {displayLines.map((l, j) => (
                        <Box component="span" key={j} sx={{ display: "block" }}>
                          {l}
                        </Box>
                      ))}
                    </Typography>
                  );
                })}
              </Box>
            </Paper>
          ))}
        </Box>
      </Box>
    </MainLayout>
  );
};

export default TechnicalSupport;