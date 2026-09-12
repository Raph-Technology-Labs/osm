import { useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableRow,
  TextField,
  Typography,
  Autocomplete,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ArrowDropDownIcon from "@mui/icons-material/ArrowDropDown";
import ClearIcon from "@mui/icons-material/Clear";
import CameraAltIcon from "@mui/icons-material/CameraAlt";
import { useNavigate } from "react-router-dom";
import usePartImage from "../hooks/usePartImage";

import api from "../api/axios";

const PartSelectionPage = () => {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const navigate = useNavigate();

  // ── Categories ─────────────────────────────────────────────────
  const [categories, setCategories] = useState([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  const [categoriesError, setCategoriesError] = useState(false);
  const [selectedCategoryId, setSelectedCategoryId] = useState("");

  // ── Parts ──────────────────────────────────────────────────────
  const [parts, setParts] = useState([]);
  const [partsLoading, setPartsLoading] = useState(false);
  const [partsError, setPartsError] = useState(false);

  const [selectedPart, setSelectedPart] = useState(null);
  const [partInput, setPartInput] = useState("");

  // ── Barcode ────────────────────────────────────────────────────
  const scannerRef = useRef(null);
  const [scanStatus, setScanStatus] = useState(null); // { type, message }

  // ── Session start ──────────────────────────────────────────────
  const [sessionStarting, setSessionStarting] = useState(false);
  const [sessionStartError, setSessionStartError] = useState("");

  
  // Load categories once.
  useEffect(() => {
    setCategoriesLoading(true);
    setCategoriesError(false);
    api
      .get("/parts/categories")
      .then(({ data }) => setCategories(data))
      .catch(() => setCategoriesError(true))
      .finally(() => setCategoriesLoading(false));
  }, []);

  // Load parts whenever the category changes. No Submit gate — picking a
  // category is the confirmation.
  useEffect(() => {
    setSelectedPart(null);
    setPartInput("");
    setSessionStartError("");

    if (!selectedCategoryId) {
      setParts([]);
      return;
    }

    setPartsLoading(true);
    setPartsError(false);
    api
      .get("/parts", { params: { category_id: selectedCategoryId } })
      .then(({ data }) => setParts(data))
      .catch(() => {
        setParts([]);
        setPartsError(true);
      })
      .finally(() => setPartsLoading(false));
  }, [selectedCategoryId]);

  // Keep the scanner field focused so a wedge scanner always lands in it.
  useEffect(() => {
    scannerRef.current?.focus();
  }, [selectedCategoryId]);

  // Barcode resolves against the parts already loaded for this category.
  const handleBarcodeScanned = (scannedCode) => {
    const code = (scannedCode || "").trim();
    if (!code) return;

    if (!selectedCategoryId) {
      setScanStatus({ type: "error", message: "Choose a category before scanning." });
      return;
    }

    const match = parts.find(
      (p) => p.part_code?.toLowerCase() === code.toLowerCase(),
    );

    if (!match) {
      setSelectedPart(null);
      setPartInput("");
      setScanStatus({
        type: "error",
        message: `No part with code "${code}" in this category.`,
      });
      return;
    }

    setSelectedPart(match);
    setPartInput(match.part_name);
    setSessionStartError("");
    setScanStatus({ type: "success", message: `Scanned: ${match.part_name}` });
  };

  const handleScannerKeyDown = (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    handleBarcodeScanned(e.target.value);
    e.target.value = "";
  };

  const handleStartSession = async () => {
    if (!selectedPart) return;
    setSessionStarting(true);
    setSessionStartError("");
    try {
      await api.post("/inspection/session/start", {
        part_code: selectedPart.part_code,
      });
      navigate(
        `/inspection?part_id=${selectedPart.part_id}&part_code=${encodeURIComponent(
          selectedPart.part_code,
        )}`,
      );
    } catch (err) {
      setSessionStartError(
        err?.response?.data?.detail ||
          "Failed to start the session for that part — machine may not be ready. Try again.",
      );
    } finally {
      setSessionStarting(false);
    }
  };

  const selectedCategoryName =
    categories.find((c) => c.category_id === selectedCategoryId)?.category_name || "";

  // defects: { class_name: { conf_thresh, severity, notes } }
  const defectRows = useMemo(() => {
    const d = selectedPart?.defects;
    if (!d || typeof d !== "object") return [];
    return Object.entries(d).map(([name, cfg]) => ({
      name,
      conf_thresh: cfg?.conf_thresh,
      severity: cfg?.severity,
    }));
  }, [selectedPart]);

  // PartImage
  const partImageUrl = usePartImage(selectedPart?.part_id, selectedPart?.has_image);



  // dimensions: { param: { nominal, upper_limit, lower_limit, unit, notes } }
  const dimensionRows = useMemo(() => {
    const dims = selectedPart?.dimensions;
    if (!dims || typeof dims !== "object") return [];
    return Object.entries(dims).map(([param, spec]) => ({
      param,
      nominal: spec?.nominal,
      upper_limit: spec?.upper_limit,
      lower_limit: spec?.lower_limit,
      unit: spec?.unit,
    }));
  }, [selectedPart]);

  const detailRows = [
    { label: "Category", value: selectedCategoryName },
    { label: "Part Code", value: selectedPart?.part_code },
    { label: "Part Name", value: selectedPart?.part_name },
    {
      label: "Part Weight",
      value:
        selectedPart?.part_weight != null
          ? `${selectedPart.part_weight} g (per piece)`
          : null,
    },
  ];

  return (
    <Box
      sx={{
        minHeight: "100%",
        height: "100%",
        overflowY: "auto",
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        p: { xs: 1.5, sm: 3 },
      }}
    >
      <Paper
        elevation={0}
        sx={{
          width: "100%",
          maxWidth: 1300,
          p: { xs: 2.5, sm: 4, md: 5 },
          my: { xs: 1, sm: 2 },
          borderRadius: 3,
          bgcolor: "background.paper",
          border: "1px solid",
          borderColor: "divider",
        }}
      >
        {/* ── Header ───────────────────────────────────────────── */}
        <Box sx={{ mb: 2 }}>
          <Typography variant="h4" sx={{ fontWeight: 700, mb: 0.5 }}>
            New Session — Select Part
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Choose a category, then find the part by name, code, or barcode scan.
          </Typography>
        </Box>

        {categoriesError && (
          <Typography color="error" sx={{ mb: 2 }}>
            Failed to load categories.
          </Typography>
        )}

        {/* ── Scan prompt strip ─────────────────────────────────── */}
        <Box
          onClick={() => scannerRef.current?.focus()}
          sx={{
            border: "2px dashed",
            borderColor: "primary.main",
            p: { xs: 1.5, sm: 2.5 },
            mb: 3,
            borderRadius: 2,
            bgcolor: "secondary.main",
            textAlign: "center",
            cursor: "pointer",
          }}
        >
          <Typography sx={{ color: "#fff", fontWeight: 600 }}>
            Scan the barcode for the item
          </Typography>
        </Box>

        <Box
          sx={{
            display: "flex",
            flexDirection: { xs: "column", md: "row" },
            gap: { xs: 2, md: 4 },
          }}
        >
          {/* ── LEFT: selection controls ───────────────────────── */}
          <Box sx={{ flex: 1.2, minWidth: 0 }}>
            <Typography sx={{ mb: 1, fontWeight: 600 }}>Part Category</Typography>
            <FormControl fullWidth sx={{ mb: 2.5 }}>
              <Select
                displayEmpty
                value={selectedCategoryId}
                onChange={(e) => setSelectedCategoryId(e.target.value)}
                disabled={categoriesLoading || categoriesError}
              >
                <MenuItem value="">
                  {categoriesLoading ? "Loading categories…" : "-- Choose Category --"}
                </MenuItem>
                {categories.map((cat) => (
                  <MenuItem key={cat.category_id} value={cat.category_id}>
                    {cat.category_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {selectedCategoryId && !partsLoading && !partsError && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Total parts in <b>{selectedCategoryName}</b>: {parts.length}
              </Typography>
            )}

            <Typography sx={{ mb: 1, fontWeight: 600 }}>Part Name</Typography>
            <Autocomplete
              fullWidth
              disabled={!selectedCategoryId || sessionStarting}
              options={parts}
              value={selectedPart}
              inputValue={partInput}
              onInputChange={(e, v) => setPartInput(v)}
              onChange={(e, v) => {
                setSelectedPart(v || null);
                setPartInput(v?.part_name || "");
                setScanStatus(null);
                setSessionStartError("");
              }}
              getOptionLabel={(option) => option?.part_name || ""}
              getOptionKey={(option) => option.part_code}
              isOptionEqualToValue={(a, b) => a.part_code === b.part_code}
              filterOptions={(options, { inputValue }) => {
                const input = inputValue.toLowerCase();
                return options.filter(
                  (option) =>
                    option.part_name?.toLowerCase().includes(input) ||
                    option.part_code?.toLowerCase().includes(input),
                );
              }}
              popupIcon={<ArrowDropDownIcon />}
              clearIcon={<ClearIcon />}
              renderOption={(props, option) => (
                <li {...props} key={option.part_code}>
                  <Box>
                    <Typography variant="body2">{option.part_name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {option.part_code}
                    </Typography>
                  </Box>
                </li>
              )}
              renderInput={(params) => (
                <TextField
                  {...params}
                  placeholder={
                    selectedCategoryId
                      ? "Type part name or code"
                      : "Choose a category first"
                  }
                />
              )}
              sx={{ mb: 1 }}
            />

            {partsError && (
              <Typography color="error" variant="body2" sx={{ mb: 2 }}>
                Failed to load parts for this category.
              </Typography>
            )}
            {!partsLoading && !partsError && selectedCategoryId && parts.length === 0 && (
              <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>
                No parts in this category yet.
              </Typography>
            )}

            <Typography sx={{ mt: 2, mb: 1, fontWeight: 600 }}>
              Scan Part Code
            </Typography>
            <TextField
              inputRef={scannerRef}
              fullWidth
              autoComplete="off"
              disabled={!selectedCategoryId || sessionStarting}
              placeholder="Waiting for scan…"
              onKeyDown={handleScannerKeyDown}
            />
            {scanStatus && (
              <Typography
                variant="body2"
                color={scanStatus.type === "error" ? "error" : "success.main"}
                sx={{ mt: 1 }}
              >
                {scanStatus.message}
              </Typography>
            )}
          </Box>

          {/* ── RIGHT: image + actions ─────────────────────────── */}
          <Box sx={{ flex: 1, display: "flex", flexDirection: "column", gap: 2 }}>
                          <Box
                sx={{
                  display: "flex",
                  justifyContent: "center",
                  alignItems: "center",
                  border: "1px dashed",
                  borderColor: "divider",
                  borderRadius: 2,
                  bgcolor: "background.default",
                  minHeight: { xs: 160, md: 220 },
                  overflow: "hidden",
                }}
              >
                {partImageUrl ? (
                  <Box
                    component="img"
                    src={partImageUrl}
                    alt={selectedPart?.part_name || "Part"}
                    sx={{ maxWidth: "100%", maxHeight: 220, objectFit: "contain" }}
                  />
                ) : (
                  <Typography color="text.secondary">
                    <CameraAltIcon fontSize="small" />{" "}
                    {selectedPart?.has_image ? "Loading image…" : "Part image"}
                  </Typography>
                )}
              </Box>

            <Box sx={{ display: "flex", gap: 2 }}>
              <Button
                variant="outlined"
                color="secondary"
                fullWidth
                disabled={sessionStarting}
                onClick={() => navigate(-1)}
              >
                Cancel
              </Button>
              <Button
                variant="contained"
                color="primary"
                fullWidth
                disabled={!selectedPart || sessionStarting}
                onClick={handleStartSession}
              >
                {sessionStarting ? (
                  <CircularProgress size={24} color="inherit" />
                ) : (
                  "Start Session"
                )}
              </Button>
            </Box>

            {sessionStartError && (
              <Typography color="error" variant="body2">
                {sessionStartError}
              </Typography>
            )}
          </Box>
        </Box>

        <Divider sx={{ my: 4 }} />

        {/* ── Part details ──────────────────────────────────────── */}
        <Typography variant="h6" sx={{ mb: 2, fontWeight: 700 }}>
          Part Details
        </Typography>

        <TableContainer
          component={Paper}
          elevation={0}
          sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}
        >
          <Table size={isMobile ? "small" : "medium"}>
            <TableBody>
              {detailRows.map((row) => (
                <TableRow key={row.label}>
                  <TableCell
                    sx={{
                      width: { xs: "40%", sm: "30%" },
                      fontWeight: 600,
                      bgcolor: "background.default",
                    }}
                  >
                    {row.label}
                  </TableCell>
                  <TableCell>{row.value ?? "—"}</TableCell>
                </TableRow>
              ))}

              <TableRow>
                <TableCell sx={{ fontWeight: 600, bgcolor: "background.default" }}>
                  Pipelines
                </TableCell>
                <TableCell>
                  {selectedPart ? (
                    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
                      <Chip
                        size="small"
                        label="Defect Detection"
                        color={selectedPart.has_defect_pipeline ? "warning" : "default"}
                        variant={selectedPart.has_defect_pipeline ? "filled" : "outlined"}
                      />
                      <Chip
                        size="small"
                        label="Measurement"
                        color={selectedPart.has_measurement_pipeline ? "info" : "default"}
                        variant={
                          selectedPart.has_measurement_pipeline ? "filled" : "outlined"
                        }
                      />
                    </Box>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>

              {selectedPart?.has_defect_pipeline && (
                <TableRow>
                  <TableCell sx={{ fontWeight: 600, bgcolor: "background.default" }}>
                    Defects to Check
                  </TableCell>
                  <TableCell>
                    {defectRows.length > 0 ? (
                      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
                        {defectRows.map((d) => (
                          <Chip
                            key={d.name}
                            size="small"
                            variant="outlined"
                            color={d.severity === "critical" ? "error" : "warning"}
                            label={
                              d.conf_thresh != null
                                ? `${d.name} · ≥${d.conf_thresh}`
                                : d.name
                            }
                          />
                        ))}
                      </Box>
                    ) : (
                      "No defects configured for this part yet"
                    )}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>

        {selectedPart?.has_measurement_pipeline && (
          <>
            <Typography variant="h6" sx={{ mt: 4, mb: 2, fontWeight: 700 }}>
              Measurement Parameters
            </Typography>
            <TableContainer
              component={Paper}
              elevation={0}
              sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}
            >
              <Table size={isMobile ? "small" : "medium"}>
                <TableBody>
                  {dimensionRows.length > 0 ? (
                    dimensionRows.map((row) => (
                      <TableRow key={row.param}>
                        <TableCell
                          sx={{
                            width: { xs: "40%", sm: "30%" },
                            fontWeight: 600,
                            bgcolor: "background.default",
                          }}
                        >
                          {row.param}
                        </TableCell>
                        <TableCell>
                          Nominal: {row.nominal ?? "—"} &nbsp;|&nbsp; Lower:{" "}
                          {row.lower_limit ?? "—"} &nbsp;|&nbsp; Upper:{" "}
                          {row.upper_limit ?? "—"}
                          {row.unit ? ` (${row.unit})` : ""}
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={2} sx={{ color: "text.secondary" }}>
                        No measurement parameters configured for this part yet.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </>
        )}
      </Paper>
    </Box>
  );
};

export default PartSelectionPage;