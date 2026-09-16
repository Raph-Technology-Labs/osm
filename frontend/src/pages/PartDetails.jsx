import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { useNavigate } from "react-router-dom";

import api from "../api/axios";
import { useAuth } from "../auth/AuthContext";

// ─────────────────────────────────────────────────────────────────
// Endpoints. Categories come from the existing operator router; the
// rest from part_details, which has its own prefix so it cannot
// collide with parts.py / parts_admin.py / dashboard.py.
// ─────────────────────────────────────────────────────────────────
const EP = {
  categories: "/parts/categories",
  list: "/part-details/parts",
  byCode: "/part-details/by-code",
  part: (id) => `/part-details/parts/${id}`,
  image: (id) => `/part-details/parts/${id}/image`,
  export: "/part-details/export",
};

const PIPELINE_FILTERS = [
  { value: "", label: "All Pipelines" },
  { value: "defect", label: "Defect Detection" },
  { value: "measurement", label: "Measurement" },
  { value: "both", label: "Defect + Measurement" },
  { value: "none", label: "Not Configured" },
];

// Same list AddNewPartPage offers, so a part edited here keeps units
// the Add Part form would have produced.
const UNIT_OPTIONS = ["mm", "cm", "um", "deg", "mm2", ""];

const SEVERITIES = ["", "critical", "major", "minor"];
const SEVERITY_COLOR = { critical: "error", major: "warning", minor: "default" };

const numeric = (v) => v === "" || /^-?[0-9]*\.?[0-9]*$/.test(v);
const nonNegative = (v) => v === "" || /^[0-9]*\.?[0-9]*$/.test(v);

const inputSx = {
  "& .MuiOutlinedInput-root": {
    height: 44,
    borderRadius: 1.5,
    bgcolor: "background.paper",
  },
  "& .MuiOutlinedInput-input": { padding: "10px 12px", fontSize: "0.9rem" },
  "& .MuiInputLabel-root": { fontSize: "0.85rem" },
};

const cardSx = {
  bgcolor: "background.paper",
  borderRadius: 2,
  boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
};

// Part.defects → { <defect name>: { conf_thresh, severity?, notes? } }
// Name is free-hand: it has to match the detection model's class name.
const emptyDefect = () => ({
  defect_name: "",
  conf_thresh: "",
  severity: "",
  notes: "",
});

// Part.dimensions → { <parameter name>: { nominal, lower_limit, upper_limit,
//                                          unit, calibration_factor, notes } }
const emptyDimension = () => ({
  param_name: "",
  nominal: "",
  lower_limit: "",
  upper_limit: "",
  unit: "mm",
  calibration_factor: "",
  notes: "",
});

const num = (v) => (v === null || v === undefined ? "" : v);

/* stored JSON -> editable rows */
const dimensionsToRows = (d) => {
  const rows = Object.entries(d || {}).map(([param_name, v]) => ({
    param_name,
    nominal: num(v.nominal),
    lower_limit: num(v.lower_limit),
    upper_limit: num(v.upper_limit),
    unit: v.unit ?? "",
    calibration_factor: num(v.calibration_factor),
    notes: v.notes ?? "",
  }));
  return rows.length ? rows : [emptyDimension()];
};

const defectsToRows = (d) => {
  const rows = Object.entries(d || {}).map(([defect_name, v]) => ({
    defect_name,
    conf_thresh: num(v.conf_thresh),
    severity: v.severity ?? "",
    notes: v.notes ?? "",
  }));
  return rows.length ? rows : [emptyDefect()];
};

const Section = ({ title, subtitle, children }) => (
  <Box sx={{ mb: 3 }}>
    <Typography
      variant="subtitle2"
      sx={{ fontWeight: 700, color: "text.primary", mb: subtitle ? 0.25 : 1 }}
    >
      {title}
    </Typography>
    {subtitle && (
      <Typography
        variant="caption"
        sx={{ color: "text.secondary", display: "block", mb: 1.25 }}
      >
        {subtitle}
      </Typography>
    )}
    {children}
  </Box>
);

const PartDetails = () => {
  const theme = useTheme();
  const navigate = useNavigate();

  // Read the context rather than take a prop -- the route renders this
  // component with no props.
  const { user, isAdmin, isSuperAdmin } = useAuth();
  const role = user?.role;
  const canEdit = Boolean(isAdmin || isSuperAdmin);

  const [toast, setToast] = useState(null); // { severity, message }
  const notify = (severity, message) => setToast({ severity, message });
  const apiError = (err, fallback) =>
    notify("error", err?.response?.data?.detail || fallback);

  const [categories, setCategories] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState("");
  const [selectedPipeline, setSelectedPipeline] = useState("");
  const [selectedPart, setSelectedPart] = useState("");
  
  const [parts, setParts] = useState([]);
  const [filteredParts, setFilteredParts] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [imgVersion, setImgVersion] = useState(0); // cache-bust after save

  const [editOpen, setEditOpen] = useState(false);
  const [editPart, setEditPart] = useState({});
  const [editDims, setEditDims] = useState([emptyDimension()]);
  const [editDefects, setEditDefects] = useState([emptyDefect()]);
  const [newImage, setNewImage] = useState(null); // data URI, or null
  const [clearImage, setClearImage] = useState(false);
  const [saving, setSaving] = useState(false);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [partToDelete, setPartToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const [exporting, setExporting] = useState(false);

  const scannerRef = useRef(null);

  // ── data loading ─────────────────────────────────────────────

  const fetchParts = useCallback(
    async (categoryId, pipeline, after = null) => {
      setLoading(true);
      try {
        const params = {};
        if (categoryId) params.category_id = categoryId;
        if (pipeline) params.pipeline = pipeline;
        const { data } = await api.get(EP.list, { params });
        setParts(data);
        setFilteredParts(data);
        if (after) after(data);
      } catch (err) {
        apiError(err, "Failed to load parts.");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(EP.categories);
        setCategories(data);
      } catch {
        notify("error", "Failed to load categories.");
      }
    })();
    fetchParts("", "");
  }, [fetchParts]);

  const handleCategoryChange = (e) => {
    const id = e.target.value;
    setSelectedCategory(id);
    setSelectedPart(""); 
    setSearchTerm("");
    fetchParts(id, selectedPipeline);
  };

  const handlePipelineChange = (e) => {
    const p = e.target.value;
    setSelectedPipeline(p);
    setSelectedPart(""); 
    setSearchTerm("");
    fetchParts(selectedCategory, p);
  };

  // Filters the table down to one part. Purely local -- `parts` already
  // holds everything in the selected category.
  const handlePartChange = (e) => {
    const id = e.target.value;
    setSelectedPart(id);
    setSearchTerm("");
    setFilteredParts(id ? parts.filter((p) => p.part_id === id) : parts);
  };


  const localFilter = (code) => {
    if (!code) {
      setFilteredParts(parts);
      return;
    }
    const q = code.toLowerCase();
    setFilteredParts(
      parts.filter(
        (p) =>
          p.part_name?.toLowerCase().includes(q) ||
          p.part_code?.toLowerCase().includes(q),
      ),
    );
  };

  // Scan: match the loaded list first, else look the code up globally and
  // jump to that part's category.
  const handleSearch = async (codeOverride) => {
    const code = typeof codeOverride === "string" ? codeOverride : searchTerm;
    setSelectedPart("");          // ← add
    if (!code) {
      setFilteredParts(parts);
      return;
    }

    const local = parts.find(
      (p) => p.part_code?.toLowerCase() === code.toLowerCase(),
    );
    if (local) {
      setFilteredParts([local]);
      return;
    }

    try {
      const { data } = await api.get(EP.byCode, { params: { part_code: code } });
      if (data?.category_id) {
        setSelectedCategory(data.category_id);
        fetchParts(data.category_id, selectedPipeline, (fresh) => {
          const exact = fresh.filter(
            (p) => p.part_code?.toLowerCase() === code.toLowerCase(),
          );
          setFilteredParts(exact.length ? exact : fresh);
          notify("success", `Found in category: ${data.category_name}`);
        });
      } else {
        setFilteredParts([data]);
        notify("success", `Found "${data.part_code}" (no category assigned)`);
      }
    } catch {
      localFilter(code);
      notify("warning", `No part with code "${code}".`);
    }
  };

  // ── edit dialog ──────────────────────────────────────────────

  const openEdit = (part) => {
    setEditPart({ ...part });
    setEditDims(dimensionsToRows(part.dimensions));
    setEditDefects(defectsToRows(part.defects));
    setNewImage(null);
    setClearImage(false);
    setEditOpen(true);
  };

  const setField = (key) => (e) =>
    setEditPart((p) => ({ ...p, [key]: e.target.value }));

  const addDim = () => setEditDims((d) => [...d, emptyDimension()]);
  const removeDim = (i) =>
    setEditDims((d) => (i === 0 && d.length === 1 ? [emptyDimension()] : d.filter((_, x) => x !== i)));
  const updateDim = (i, field, value) =>
    setEditDims((d) => d.map((r, x) => (x === i ? { ...r, [field]: value } : r)));

  const addDefect = () => setEditDefects((d) => [...d, emptyDefect()]);
  const removeDefect = (i) =>
    setEditDefects((d) => (i === 0 && d.length === 1 ? [emptyDefect()] : d.filter((_, x) => x !== i)));
  const updateDefect = (i, field, value) =>
    setEditDefects((d) => d.map((r, x) => (x === i ? { ...r, [field]: value } : r)));

  // Mirrors AddNewPartPage's rules and the Pydantic validators, so the
  // problem surfaces before a round trip. The server still enforces it.
  const validate = () => {
    if (!editPart.part_name?.trim()) return "Part name is required.";

    const namedDefects = editDefects.filter((d) => d.defect_name.trim());
    const defectKeys = namedDefects.map((d) => d.defect_name.trim().toLowerCase());
    const dupeDefect = defectKeys.find((k, i) => defectKeys.indexOf(k) !== i);
    if (dupeDefect) return `Duplicate defect "${dupeDefect}".`;

    for (const d of namedDefects) {
      if (d.conf_thresh !== "") {
        const v = Number(d.conf_thresh);
        if (v < 0 || v > 1)
          return `${d.defect_name}: confidence threshold must be between 0 and 1.`;
      }
    }

    const namedDims = editDims.filter((d) => d.param_name.trim());
    const dimKeys = namedDims.map((d) => d.param_name.trim().toLowerCase());
    const dupeDim = dimKeys.find((k, i) => dimKeys.indexOf(k) !== i);
    if (dupeDim) return `Duplicate parameter "${dupeDim}".`;

    for (const d of namedDims) {
      const { lower_limit: lo, upper_limit: hi, nominal: nom } = d;
      if (lo === "" && hi === "")
        return `${d.param_name}: set at least a lower or upper tolerance — a parameter with no limits can never fail.`;
      if (lo !== "" && hi !== "" && Number(lo) > Number(hi))
        return `${d.param_name}: lower tolerance cannot be greater than upper.`;
      if (nom !== "" && lo !== "" && Number(nom) < Number(lo))
        return `${d.param_name}: nominal is below the lower tolerance.`;
      if (nom !== "" && hi !== "" && Number(nom) > Number(hi))
        return `${d.param_name}: nominal is above the upper tolerance.`;
      if (d.calibration_factor !== "" && Number(d.calibration_factor) <= 0)
        return `${d.param_name}: calibration factor must be greater than 0.`;
    }

    return null;
  };

  const buildDimensions = () => {
    const out = {};
    editDims.forEach((d) => {
      const key = d.param_name.trim();
      if (!key) return;
      out[key] = {
        ...(d.nominal !== "" && { nominal: Number(d.nominal) }),
        ...(d.lower_limit !== "" && { lower_limit: Number(d.lower_limit) }),
        ...(d.upper_limit !== "" && { upper_limit: Number(d.upper_limit) }),
        ...(d.unit && { unit: d.unit }),
        ...(d.calibration_factor !== "" && {
          calibration_factor: Number(d.calibration_factor),
        }),
        ...(d.notes?.trim() && { notes: d.notes.trim() }),
      };
    });
    return out;
  };

  const buildDefects = () => {
    const out = {};
    editDefects.forEach((d) => {
      const key = d.defect_name.trim();
      if (!key) return;
      out[key] = {
        ...(d.conf_thresh !== "" && { conf_thresh: Number(d.conf_thresh) }),
        ...(d.severity && { severity: d.severity }),
        ...(d.notes?.trim() && { notes: d.notes.trim() }),
      };
    });
    return out;
  };

    const handleSave = async () => {
    const err = validate();
    if (err) return notify("error", err);

    const payload = {
      part_name: editPart.part_name.trim(),
      category_id: editPart.category_id || null,
      part_weight:
        editPart.part_weight === "" || editPart.part_weight == null
          ? null
          : Number(editPart.part_weight),
      notes: editPart.notes?.trim() || null,
      dimensions: buildDimensions(),
      defects: buildDefects(),
      ...(newImage && { image: newImage }),
      clear_image: clearImage,
    };

    setSaving(true);
    try {
      await api.put(EP.part(editPart.part_id), payload);
      setEditOpen(false);
      setImgVersion((v) => v + 1);
      notify("success", `Part "${editPart.part_code}" updated.`);
      // Refetch wipes filteredParts back to the full list, so re-apply
      // whichever narrowing was active before the save.
      fetchParts(selectedCategory, selectedPipeline, (fresh) => {
        if (selectedPart) {
          setFilteredParts(fresh.filter((p) => p.part_id === selectedPart));
        } else if (searchTerm) {
          localFilter(searchTerm);
        }
      });
    } catch (e) {
      apiError(e, "Failed to update part.");
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    setDeleting(true);
    try {
      await api.delete(EP.part(partToDelete.part_id));
      setDeleteOpen(false);
      notify("warning", `Part "${partToDelete.part_code}" deleted.`);
      setPartToDelete(null);
      fetchParts(selectedCategory, selectedPipeline);
    } catch (e) {
      apiError(e, "Failed to delete part.");
    } finally {
      setDeleting(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const res = await api.get(EP.export, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `OSM_PartsData_${new Date().toISOString().split("T")[0]}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch {
      notify("error", "Failed to export parts data.");
    } finally {
      setExporting(false);
    }
  };

  // api.defaults.baseURL so the <img> resolves the same host the axios
  // instance talks to -- a bare src would hit the dev server instead.
  const imageSrc = (partId) =>
    `${(api.defaults.baseURL || "").replace(/\/+$/, "")}${EP.image(partId)}?v=${imgVersion}`;

  const editPreview = () => {
    if (clearImage) return null;
    if (newImage) return newImage;
    if (editPart.has_image) return imageSrc(editPart.part_id);
    return null;
  };

  // ── render ───────────────────────────────────────────────────

  return (
    <Box sx={{ height: "100%", minHeight: 0, overflowY: "auto", bgcolor: "background.default" }}>
      <Box sx={{ maxWidth: 1400, mx: "auto", px: { xs: 1.5, sm: 3, md: 4 }, py: { xs: 2, md: 3 } }}>

        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1.5}
          alignItems={{ xs: "flex-start", sm: "center" }}
          justifyContent="space-between"
          sx={{ mb: 3 }}
        >
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Part Details
            </Typography>
            <Typography variant="body2" sx={{ color: "text.secondary" }}>
              Browse, search, edit or export configured parts.
            </Typography>
          </Box>

          {canEdit && (
            <Button
              variant="contained"
              startIcon={<SettingsOutlinedIcon />}
              onClick={() => navigate("/part-config")}
              sx={{
                whiteSpace: "nowrap",
                bgcolor: "common.black",
                color: "common.white",
                "&:hover": { bgcolor: "grey.800" },
              }}
            >
              Machine Config
            </Button>
          )}
        </Stack>

        {!canEdit && (
          <Alert severity="info" sx={{ mb: 3 }}>
            You are signed in as <b>{role || "an operator"}</b> — this page is
            read-only. Editing parts requires administrator rights.
          </Alert>
        )}

        {/* Filters */}
        <Box sx={{ ...cardSx, p: { xs: 2, sm: 2.5 }, mb: 3 }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
            <FormControl sx={{ minWidth: 210, ...inputSx }}>
              <InputLabel>Category</InputLabel>
              <Select value={selectedCategory} onChange={handleCategoryChange} label="Category">
                <MenuItem value="">All Categories</MenuItem>
                {categories.map((c) => (
                  <MenuItem key={c.category_id} value={c.category_id}>
                    {c.category_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

                        <FormControl sx={{ minWidth: 240, ...inputSx }} disabled={!parts.length}>
              <InputLabel>Part</InputLabel>
              <Select value={selectedPart} onChange={handlePartChange} label="Part">
                <MenuItem value="">
                  All Parts{parts.length ? ` (${parts.length})` : ""}
                </MenuItem>
                {parts.map((p) => (
                  <MenuItem key={p.part_id} value={p.part_id}>
                    {p.part_name} — {p.part_code}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <FormControl sx={{ minWidth: 220, ...inputSx }}>
              <InputLabel>Pipeline</InputLabel>
              <Select value={selectedPipeline} onChange={handlePipelineChange} label="Pipeline">
                {PIPELINE_FILTERS.map((p) => (
                  <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>
                ))}
              </Select>
            </FormControl>

            <Box
              sx={{
                display: "flex", alignItems: "center", gap: 1, px: 1.5, height: 44,
                bgcolor: "background.default", borderRadius: 1.5,
                border: 1, borderColor: "divider",
              }}
            >
              <Typography sx={{ fontWeight: 600, fontSize: "0.85rem" }}>
                Scanner:
              </Typography>
              <input
                ref={scannerRef}
                autoFocus
                className="ignore-virtual-keyboard"
                placeholder="Scan barcode..."
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    const code = e.target.value.trim();
                    if (code) {
                      setSearchTerm(code);
                      handleSearch(code);
                    }
                    e.target.value = "";
                  }
                }}
                style={{
                  border: `1px solid ${theme.palette.divider}`,
                  borderRadius: 6,
                  padding: "7px 10px",
                  outline: "none",
                  width: 170,
                }}
              />
            </Box>

            <TextField
              placeholder="Search name or code"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              sx={{ width: 240, ...inputSx }}
              InputProps={{
                startAdornment: <InputAdornment position="start">🔍</InputAdornment>,
              }}
            />

            <Button variant="contained" sx={{ height: 44 }} onClick={() => handleSearch()}>
              Search
            </Button>
            <Button
              variant="outlined"
              sx={{ height: 44 }}
              onClick={handleExport}
              disabled={exporting}
            >
              {exporting ? "Preparing..." : "Export"}
            </Button>
          </Box>
        </Box>

        {/* Table */}
        <TableContainer
          component={Paper}
          elevation={0}
          sx={{
            borderRadius: 2, border: 1, borderColor: "divider", overflowX: "auto",
            "& .MuiTableCell-root": { padding: "10px 8px" },
          }}
        >
          <Table sx={{ width: "100%", minWidth: 1000, tableLayout: "fixed" }}>
            <TableHead>
              <TableRow sx={{ "& th": { bgcolor: "background.default", fontWeight: 700 } }}>
                <TableCell align="center" sx={{ width: "4%" }}>#</TableCell>
                <TableCell align="center" sx={{ width: "16%" }}>Part Name</TableCell>
                <TableCell align="center" sx={{ width: "13%" }}>Part Code</TableCell>
                <TableCell align="center" sx={{ width: "8%" }}>Image</TableCell>
                <TableCell align="center" sx={{ width: "12%" }}>Category</TableCell>
                <TableCell align="center" sx={{ width: "15%" }}>Pipeline</TableCell>
                <TableCell align="center" sx={{ width: "11%" }}>Params / Defects</TableCell>
                <TableCell align="center" sx={{ width: "8%" }}>Config</TableCell>
                <TableCell align="center" sx={{ width: "13%" }}>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={9} align="center" sx={{ py: 4, color: "text.secondary" }}>
                    Loading…
                  </TableCell>
                </TableRow>
              ) : filteredParts.length > 0 ? (
                filteredParts.map((part, index) => {
                  const dimCount = Object.keys(part.dimensions || {}).length;
                  const defectCount = Object.keys(part.defects || {}).length;
                  return (
                    <TableRow key={part.part_id} hover>
                      <TableCell align="center">{index + 1}</TableCell>
                      <TableCell align="center">{part.part_name}</TableCell>
                      <TableCell align="center">{part.part_code}</TableCell>
                      <TableCell align="center">
                        {part.has_image ? (
                          <img
                            src={imageSrc(part.part_id)}
                            alt={part.part_name || "Part"}
                            loading="lazy"
                            style={{ width: 56, height: 56, objectFit: "cover", borderRadius: 8 }}
                          />
                        ) : "—"}
                      </TableCell>
                      <TableCell align="center">{part.category_name || "—"}</TableCell>
                      <TableCell align="center">
                        <Stack direction="row" spacing={0.5} justifyContent="center" flexWrap="wrap" useFlexGap>
                          {part.has_defect_pipeline && (
                            <Chip size="small" label="Defect" color="primary" variant="outlined" />
                          )}
                          {part.has_measurement_pipeline && (
                            <Chip size="small" label="Measure" color="secondary" variant="outlined" />
                          )}
                          {!part.has_defect_pipeline && !part.has_measurement_pipeline && (
                            <Chip size="small" label="Not configured" variant="outlined" />
                          )}
                        </Stack>
                      </TableCell>
                      <TableCell align="center" sx={{ fontSize: "0.8rem", color: "text.secondary" }}>
                        {dimCount ? `${dimCount} param` : "—"}
                        {defectCount ? `, ${defectCount} defect` : ""}
                      </TableCell>
                      <TableCell align="center" sx={{ fontSize: "0.8rem", color: "text.secondary" }}>
                        {part.active_config_version ? `v${part.active_config_version}` : "—"}
                      </TableCell>
                      <TableCell align="center">
                        <Stack direction="row" spacing={1} justifyContent="center">
                          <Tooltip title={canEdit ? "" : "Administrator access required"}>
                            <span>
                              <Button
                                variant="outlined"
                                size="small"
                                disabled={!canEdit}
                                onClick={() => openEdit(part)}
                              >
                                Edit
                              </Button>
                            </span>
                          </Tooltip>
                          <Tooltip title={canEdit ? "" : "Administrator access required"}>
                            <span>
                              <Button
                                variant="outlined"
                                size="small"
                                color="error"
                                disabled={!canEdit}
                                onClick={() => {
                                  setPartToDelete(part);
                                  setDeleteOpen(true);
                                }}
                              >
                                Delete
                              </Button>
                            </span>
                          </Tooltip>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })
              ) : (
                <TableRow>
                  <TableCell colSpan={9} align="center" sx={{ py: 4, color: "text.secondary" }}>
                    No parts found
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>

      {/* ===== Edit dialog ===== */}
      <Dialog
        open={editOpen}
        onClose={() => !saving && setEditOpen(false)}
        fullWidth
        maxWidth="md"
        PaperProps={{ sx: { borderRadius: 2 } }}
      >
        <DialogTitle sx={{ fontWeight: 700 }}>
          Edit Part
          <Typography
            variant="caption"
            sx={{ display: "block", color: "text.secondary", fontWeight: 400 }}
          >
            {editPart.part_code}
          </Typography>
        </DialogTitle>

        <DialogContent dividers>
          <Box component="fieldset" disabled={saving} sx={{ border: 0, p: 0, m: 0, minWidth: 0 }}>

            <Section title="Basic Information">
              <Stack spacing={2}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <TextField
                    fullWidth
                    label="Part Name *"
                    value={editPart.part_name || ""}
                    onChange={setField("part_name")}
                    sx={inputSx}
                  />
                  <TextField
                    fullWidth
                    disabled
                    variant="filled"
                    label="Part Code"
                    value={editPart.part_code || ""}
                    helperText="Immutable — this is what the barcode scanner reads."
                  />
                </Stack>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <FormControl fullWidth sx={inputSx}>
                    <InputLabel>Category</InputLabel>
                    <Select
                      label="Category"
                      value={editPart.category_id || ""}
                      onChange={(e) =>
                        setEditPart((p) => ({ ...p, category_id: e.target.value || null }))
                      }
                    >
                      <MenuItem value="">— none —</MenuItem>
                      {categories.map((c) => (
                        <MenuItem key={c.category_id} value={c.category_id}>
                          {c.category_name}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <TextField
                    fullWidth
                    label="Weight (g)"
                    value={editPart.part_weight ?? ""}
                    inputProps={{ inputMode: "decimal" }}
                    onChange={(e) =>
                      nonNegative(e.target.value) &&
                      setEditPart((p) => ({ ...p, part_weight: e.target.value }))
                    }
                    sx={inputSx}
                  />
                </Stack>
                <TextField
                  fullWidth
                  label="Notes"
                  value={editPart.notes || ""}
                  onChange={setField("notes")}
                  sx={inputSx}
                />
              </Stack>
            </Section>

            <Divider sx={{ mb: 3 }} />

            <Section
              title="Defects"
              subtitle="Each defect this part is checked for. The name must match the detection model's class name exactly."
            >
              {editDefects.map((d, i) => (
                <Box
                  key={i}
                  sx={{ border: 1, borderColor: "divider", borderRadius: 1.5, p: 1.5, mb: 1.5 }}
                >
                  <Box
                    sx={{
                      display: "grid",
                      gridTemplateColumns: { xs: "1fr", md: "auto 1.4fr 1fr 1fr auto" },
                      gap: 1,
                      alignItems: "center",
                    }}
                  >
                    <Typography variant="caption" sx={{ color: "text.secondary", minWidth: 30 }}>
                      d{i + 1}
                    </Typography>
                    <TextField
                      label="Defect name"
                      value={d.defect_name}
                      sx={inputSx}
                      onChange={(e) => updateDefect(i, "defect_name", e.target.value)}
                    />
                    <TextField
                      label="Confidence threshold"
                      value={d.conf_thresh}
                      sx={inputSx}
                      inputProps={{ inputMode: "decimal" }}
                      error={
                        d.conf_thresh !== "" &&
                        (Number(d.conf_thresh) < 0 || Number(d.conf_thresh) > 1)
                      }
                      onChange={(e) =>
                        nonNegative(e.target.value) &&
                        updateDefect(i, "conf_thresh", e.target.value)
                      }
                    />
                    <TextField
                      select
                      label="Severity"
                      value={d.severity}
                      sx={inputSx}
                      onChange={(e) => updateDefect(i, "severity", e.target.value)}
                    >
                      {SEVERITIES.map((s) => (
                        <MenuItem key={s || "none"} value={s}>
                          {s ? (
                            <Chip
                              size="small"
                              label={s}
                              color={SEVERITY_COLOR[s]}
                              variant="outlined"
                              sx={{ textTransform: "capitalize" }}
                            />
                          ) : (
                            "— none —"
                          )}
                        </MenuItem>
                      ))}
                    </TextField>
                    <IconButton size="small" onClick={() => removeDefect(i)}>✕</IconButton>
                  </Box>
                  <TextField
                    label="Notes"
                    fullWidth
                    size="small"
                    sx={{ ...inputSx, mt: 1 }}
                    value={d.notes}
                    onChange={(e) => updateDefect(i, "notes", e.target.value)}
                  />
                </Box>
              ))}
              <Button size="small" onClick={addDefect}>+ Add another defect</Button>
            </Section>

            <Divider sx={{ mb: 3 }} />

            <Section
              title="Part Parameters"
              subtitle="Each dimension this part is measured on. The parameter name must match what the measurement step emits. The calibration factor scales the raw measurement before it is compared against the tolerances — leave it blank for no correction."
            >
              {editDims.map((d, i) => (
                <Box
                  key={i}
                  sx={{ border: 1, borderColor: "divider", borderRadius: 1.5, p: 1.5, mb: 1.5 }}
                >
                  <Box
                    sx={{
                      display: "grid",
                      gridTemplateColumns: {
                        xs: "1fr",
                        md: "auto 1.4fr 1fr 1fr 1fr 0.8fr 0.9fr auto",
                      },
                      gap: 1,
                      alignItems: "center",
                    }}
                  >
                    <Typography variant="caption" sx={{ color: "text.secondary", minWidth: 30 }}>
                      p{i + 1}
                    </Typography>
                    <TextField
                      label="Parameter name"
                      value={d.param_name}
                      sx={inputSx}
                      onChange={(e) => updateDim(i, "param_name", e.target.value)}
                    />
                    <TextField
                      label="Nominal"
                      value={d.nominal}
                      sx={inputSx}
                      inputProps={{ inputMode: "decimal" }}
                      onChange={(e) =>
                        numeric(e.target.value) && updateDim(i, "nominal", e.target.value)
                      }
                    />
                    <TextField
                      label="Lower tolerance"
                      value={d.lower_limit}
                      sx={inputSx}
                      inputProps={{ inputMode: "decimal" }}
                      onChange={(e) =>
                        numeric(e.target.value) && updateDim(i, "lower_limit", e.target.value)
                      }
                    />
                    <TextField
                      label="Upper tolerance"
                      value={d.upper_limit}
                      sx={inputSx}
                      inputProps={{ inputMode: "decimal" }}
                      onChange={(e) =>
                        numeric(e.target.value) && updateDim(i, "upper_limit", e.target.value)
                      }
                    />
                    <TextField
                      select
                      label="Unit"
                      value={d.unit}
                      sx={inputSx}
                      onChange={(e) => updateDim(i, "unit", e.target.value)}
                    >
                      {UNIT_OPTIONS.map((u) => (
                        <MenuItem key={u || "none"} value={u}>
                          {u || "— none —"}
                        </MenuItem>
                      ))}
                    </TextField>
                    <TextField
                      label="Cal. factor"
                      value={d.calibration_factor}
                      placeholder="1.000"
                      sx={inputSx}
                      inputProps={{ inputMode: "decimal" }}
                      onChange={(e) =>
                        nonNegative(e.target.value) &&
                        updateDim(i, "calibration_factor", e.target.value)
                      }
                    />
                    <IconButton size="small" onClick={() => removeDim(i)}>✕</IconButton>
                  </Box>
                  <TextField
                    label="Notes"
                    fullWidth
                    size="small"
                    sx={{ ...inputSx, mt: 1 }}
                    value={d.notes}
                    onChange={(e) => updateDim(i, "notes", e.target.value)}
                  />
                </Box>
              ))}
              <Button size="small" onClick={addDim}>+ Add another parameter</Button>
            </Section>

            <Divider sx={{ mb: 3 }} />

            <Section title="Part Image">
              <Stack direction="row" spacing={2} alignItems="center">
                <Button variant="outlined" component="label">
                  Upload Image (PNG / JPEG)
                  <input
                    type="file"
                    accept="image/png,image/jpeg"
                    hidden
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (!f) return;
                      if (f.size > 2 * 1024 * 1024) {
                        notify("error", "Image must be 2 MB or smaller.");
                        return;
                      }
                      const reader = new FileReader();
                      reader.onloadend = () => {
                        setNewImage(reader.result);
                        setClearImage(false);
                      };
                      reader.readAsDataURL(f);
                    }}
                  />
                </Button>
                {editPreview() && (
                  <>
                    <Box
                      component="img"
                      src={editPreview()}
                      alt="preview"
                      sx={{
                        width: 90, height: 90, borderRadius: 2, objectFit: "cover",
                        border: 1, borderColor: "divider",
                      }}
                    />
                    <Button
                      size="small"
                      color="error"
                      onClick={() => {
                        setNewImage(null);
                        setClearImage(true);
                      }}
                    >
                      Remove
                    </Button>
                  </>
                )}
              </Stack>
            </Section>

            <Section title="Pipeline State (read-only)">
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip
                  size="small"
                  variant="outlined"
                  label={`Defect pipeline: ${editPart.has_defect_pipeline ? "yes" : "no"}`}
                />
                <Chip
                  size="small"
                  variant="outlined"
                  label={`Measurement pipeline: ${editPart.has_measurement_pipeline ? "yes" : "no"}`}
                />
                <Chip
                  size="small"
                  variant="outlined"
                  label={`Active config: ${
                    editPart.active_config_version ? `v${editPart.active_config_version}` : "none"
                  }`}
                />
              </Stack>
              <Typography variant="caption" sx={{ color: "text.secondary", display: "block", mt: 1 }}>
                Set by the machine config, not here. Changing parameters on this
                page does not rebuild the active config.
              </Typography>
            </Section>
          </Box>
        </DialogContent>

        <DialogActions sx={{ p: 2, px: 3 }}>
          <Button onClick={() => setEditOpen(false)} color="inherit" disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleSave} disabled={saving} sx={{ px: 4 }}>
            {saving ? "Saving..." : "Save Changes"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* ===== Delete confirm ===== */}
      <Dialog
        open={deleteOpen}
        onClose={() => !deleting && setDeleteOpen(false)}
        PaperProps={{ sx: { borderRadius: 2 } }}
      >
        <DialogTitle sx={{ fontWeight: 700 }}>Confirm Deletion</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Delete part <strong>{partToDelete?.part_code}</strong>? Its saved
            machine configs go with it. A part that has run a production session
            cannot be deleted. This cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ pb: 2, px: 3 }}>
          <Button onClick={() => setDeleteOpen(false)} color="inherit" disabled={deleting}>
            Cancel
          </Button>
          <Button onClick={confirmDelete} variant="contained" color="error" disabled={deleting} autoFocus>
            {deleting ? "Deleting..." : "Yes, Delete"}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={!!toast}
        autoHideDuration={5000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert
          severity={toast?.severity || "info"}
          variant="filled"
          onClose={() => setToast(null)}
          sx={{ width: "100%" }}
        >
          {toast?.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default PartDetails;