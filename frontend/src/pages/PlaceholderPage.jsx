import { Typography } from "@mui/material";
import MainLayout from "../layouts/MainLayout";

const PlaceholderPage = ({ title }) => (
  <MainLayout title={title}>
    <Typography variant="body1" color="text.secondary">
      {title} page — coming soon.
    </Typography>
  </MainLayout>
);

export default PlaceholderPage;