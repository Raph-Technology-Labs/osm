import { Box, Typography } from "@mui/material";
import MainLayout from "../layouts/MainLayout";

const DashboardPage = () => {
  return (
    <MainLayout title="Dashboard">
      <Box>
        <Typography variant="body1">
          Dashboard content goes here.
        </Typography>
      </Box>
    </MainLayout>
  );
};

export default DashboardPage;