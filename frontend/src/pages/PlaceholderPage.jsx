import { Box, Typography } from "@mui/material";

const PlaceholderPage = ({ title }) => (
  <Box>
    <Typography variant="h5" sx={{ fontWeight: 700, mb: 3 }}>
      {title}
    </Typography>
    <Typography variant="body1" color="text.secondary">
      {title} page — coming soon.
    </Typography>
  </Box>
);

export default PlaceholderPage;