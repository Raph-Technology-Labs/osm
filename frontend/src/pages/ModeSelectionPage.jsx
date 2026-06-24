import { useState } from "react";
import {
  Box,
  Typography,
  Card,
  CardActionArea,
  CardContent,
  Dialog,
  DialogTitle,
  DialogContent,
  IconButton,
} from "@mui/material";
import { useNavigate } from "react-router-dom";
import { useTheme } from "@mui/material/styles";

import FormatListNumberedIcon from "@mui/icons-material/FormatListNumbered";
import ReportProblemOutlinedIcon from "@mui/icons-material/ReportProblemOutlined";
import StraightenIcon from "@mui/icons-material/Straighten";
import RuleFolderOutlinedIcon from "@mui/icons-material/RuleFolderOutlined";
import CloseIcon from "@mui/icons-material/Close";
import PrecisionManufacturingIcon from "@mui/icons-material/PrecisionManufacturing";
import SettingsInputComponentIcon from "@mui/icons-material/SettingsInputComponent";
import Inventory2Icon from "@mui/icons-material/Inventory2";
import WarehouseIcon from "@mui/icons-material/Warehouse";

import MainLayout from "../layouts/MainLayout";

// Must exactly match the CheckConstraint on PartOperationMode.mode_of_operation
const MODES = [
  {
    key: "Counting",
    label: "Counting",
    description: "Count parts as they pass through the line.",
    icon: FormatListNumberedIcon,
    // no direct path — opens the dialog instead
  },
  {
    key: "Defect Detection",
    label: "Defect Detection",
    description: "Inspect parts for dents, scratches, rust, missing threads.",
    icon: ReportProblemOutlinedIcon,
    path: "/part-selection?mode=Defect%20Detection",
  },
  {
    key: "Measurement",
    label: "Measurement",
    description: "Capture dimensional measurements against expected values.",
    icon: StraightenIcon,
    path: "/part-selection?mode=Measurement",
  },
  {
    key: "Measurement & Defect Detection",
    label: "Measurement & Defect Detection",
    description: "Combine dimensional checks with defect inspection.",
    icon: RuleFolderOutlinedIcon,
    path: "/part-selection?mode=Measurement%20%26%20Defect%20Detection",
  },
];

// The counting sub-types you added to PartOperationMode for Counting
const COUNTING_TYPES = [
  { key: "Conveyor", label: "Conveyor", icon: PrecisionManufacturingIcon },
  { key: "GCM", label: "GCM", icon: SettingsInputComponentIcon },
  { key: "SCM", label: "SCM", icon: SettingsInputComponentIcon },
  { key: "Batch", label: "Batch", icon: Inventory2Icon },
  { key: "Bulk", label: "Bulk", icon: WarehouseIcon },
];

const ModeSelectionPage = () => {
  const theme = useTheme();
  const navigate = useNavigate();
  const [countingDialogOpen, setCountingDialogOpen] = useState(false);

  const handleModeClick = (mode) => {
    if (mode.key === "Counting") {
      setCountingDialogOpen(true);
    } else {
      navigate(mode.path);
    }
  };

  const handleCountingTypeSelect = (countingType) => {
    setCountingDialogOpen(false);
    navigate(
      `/part-selection?mode=Counting&counting_type=${encodeURIComponent(countingType)}`
    );
  };

  return (
    <MainLayout title="New Session — Select Mode">
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "calc(100vh - 200px)",
          textAlign: "center",
        }}
      >
        <Typography variant="body1" color="text.secondary" sx={{ mb: 4 }}>
          Choose the operation mode for this session.
        </Typography>

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
            gap: 3,
            width: "100%",
            maxWidth: 720,
          }}
        >
          {MODES.map((mode) => {
            const Icon = mode.icon;
            return (
              <Card
                key={mode.key}
                elevation={0}
                sx={{
                  border: `1px solid ${theme.palette.divider}`,
                  borderRadius: 2,
                  transition: "all 0.2s ease",
                  "&:hover": {
                    borderColor: theme.palette.primary.main,
                    boxShadow: `0 4px 14px ${theme.palette.primary.light}`,
                  },
                }}
              >
                <CardActionArea
                  onClick={() => handleModeClick(mode)}
                  sx={{ p: 3, height: "100%" }}
                >
                  <CardContent sx={{ p: 0, textAlign: "left" }}>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 1 }}>
                      <Box
                        sx={{
                          width: 44,
                          height: 44,
                          borderRadius: "10px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          background: theme.palette.gradients.peach,
                          color: theme.palette.primary.main,
                        }}
                      >
                        <Icon />
                      </Box>
                      <Typography variant="h6" sx={{ fontWeight: 600 }}>
                        {mode.label}
                      </Typography>
                    </Box>
                    <Typography variant="body2" color="text.secondary">
                      {mode.description}
                    </Typography>
                  </CardContent>
                </CardActionArea>
              </Card>
            );
          })}
        </Box>
      </Box>

      {/* Counting sub-type dialog */}
      <Dialog
        open={countingDialogOpen}
        onClose={() => setCountingDialogOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{ sx: { borderRadius: 3, p: 1 } }}
      >
        <DialogTitle
          sx={{
            fontWeight: 700,
            fontSize: "1.25rem",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            pb: 1,
          }}
        >
          Select Counting Type
          <IconButton onClick={() => setCountingDialogOpen(false)} size="small">
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>

        <DialogContent sx={{ pb: 4, pt: 1 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Choose how parts will be counted for this session.
          </Typography>

          {/* Conveyor / GCM / SCM — standard styling */}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr 1fr" },
              gap: 2,
              mb: 3,
            }}
          >
            {COUNTING_TYPES.filter((t) => !["Batch", "Bulk"].includes(t.key)).map((type) => {
              const Icon = type.icon;
              return (
                <Card
                  key={type.key}
                  elevation={0}
                  sx={{
                    border: `1px solid ${theme.palette.divider}`,
                    borderRadius: 2,
                    "&:hover": {
                      borderColor: theme.palette.primary.main,
                      boxShadow: `0 4px 14px ${theme.palette.primary.light}`,
                    },
                  }}
                >
                  <CardActionArea
                    onClick={() => handleCountingTypeSelect(type.key)}
                    sx={{
                      p: 3,
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: 1.5,
                    }}
                  >
                    <Box
                      sx={{
                        width: 48,
                        height: 48,
                        borderRadius: "10px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        background: theme.palette.gradients.peach,
                        color: theme.palette.primary.main,
                        flexShrink: 0,
                      }}
                    >
                      <Icon />
                    </Box>
                    <Typography sx={{ fontWeight: 600 }}>{type.label}</Typography>
                  </CardActionArea>
                </Card>
              );
            })}
          </Box>

          {/* Batch + Bulk — distinct darker peach/accent pair, side by side */}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 2,
            }}
          >
            {COUNTING_TYPES.filter((t) => ["Batch", "Bulk"].includes(t.key)).map((type) => {
              const Icon = type.icon;
              return (
                <Card
                  key={type.key}
                  elevation={0}
                  sx={{
                    border: `1px solid ${theme.palette.accent.dark}`,
                    borderRadius: 2,
                    background: `linear-gradient(135deg, ${theme.palette.accent.main} 0%, ${theme.palette.accent.dark} 100%)`,
                    "&:hover": {
                      boxShadow: `0 4px 14px ${theme.palette.accent.dark}66`,
                    },
                  }}
                >
                  <CardActionArea
                    onClick={() => handleCountingTypeSelect(type.key)}
                    sx={{
                      p: 3,
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: 1.5,
                    }}
                  >
                    <Box
                      sx={{
                        width: 48,
                        height: 48,
                        borderRadius: "10px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        bgcolor: "rgba(255,255,255,0.55)",
                        color: theme.palette.accent.contrastText,
                        flexShrink: 0,
                      }}
                    >
                      <Icon />
                    </Box>
                    <Typography sx={{ fontWeight: 600, color: theme.palette.accent.contrastText }}>
                      {type.label}
                    </Typography>
                  </CardActionArea>
                </Card>
              );
            })}
          </Box>
        </DialogContent>
      </Dialog>
    </MainLayout>
  );
};

export default ModeSelectionPage;