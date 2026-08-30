import { useEffect, useState } from "react";
import {
  Box,
  Typography,
  Button,
  FormControl,
  Select,
  MenuItem,
  CircularProgress,
  Autocomplete,
  TextField,
} from "@mui/material";
import { useNavigate } from "react-router-dom";
import { useTheme } from "@mui/material/styles";

import MainLayout from "../layouts/MainLayout";
import api from "../api/axios";

const PartSelectionPage = () => {
  const theme = useTheme();
  const navigate = useNavigate();

  const [categories, setCategories] = useState([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  const [categoriesError, setCategoriesError] = useState(false);

  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [categoryConfirmed, setCategoryConfirmed] = useState(false);

  const [parts, setParts] = useState([]);
  const [partsLoading, setPartsLoading] = useState(false);
  const [partsError, setPartsError] = useState(false);

  const [sessionStarting, setSessionStarting] = useState(false);
  const [sessionStartError, setSessionStartError] = useState(false);

  useEffect(() => {
    setCategoriesLoading(true);
    setCategoriesError(false);
    api
      .get("/parts/categories")
      .then(({ data }) => setCategories(data))
      .catch(() => setCategoriesError(true))
      .finally(() => setCategoriesLoading(false));
  }, []);

  useEffect(() => {
    if (!categoryConfirmed || !selectedCategoryId) {
      setParts([]);
      return;
    }
    setPartsLoading(true);
    setPartsError(false);
    api
      .get("/parts", { params: { category_id: selectedCategoryId } })
      .then(({ data }) => setParts(data))
      .catch(() => setPartsError(true))
      .finally(() => setPartsLoading(false));
  }, [categoryConfirmed, selectedCategoryId]);

  const handleCategoryChange = (e) => {
    setSelectedCategoryId(e.target.value);
    setCategoryConfirmed(false);
  };

  const handleCategorySubmit = () => {
    if (!selectedCategoryId) return;
    setCategoryConfirmed(true);
  };

  const handlePartSelect = async (part) => {
    if (!part) return;
    setSessionStarting(true);
    setSessionStartError(false);
    try {
      await api.post("/inspection/session/start", { part_code: part.part_code });
      navigate(`/inspection?part_id=${part.part_id}&part_code=${encodeURIComponent(part.part_code)}`);
    } catch {
      setSessionStartError(true);
    } finally {
      setSessionStarting(false);
    }
  };

  return (
    <MainLayout title="New Session — Select Part">
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Choose a category, then find the part by name or code.
      </Typography>

      <Box sx={{ display: "flex", gap: 2, alignItems: "flex-start", mb: 4 }}>
        <FormControl sx={{ minWidth: 280 }}>
          <Select
            displayEmpty
            value={selectedCategoryId}
            onChange={handleCategoryChange}
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

        <Button
          variant="contained"
          color="primary"
          disabled={!selectedCategoryId}
          onClick={handleCategorySubmit}
          sx={{ height: 56 }}
        >
          Submit
        </Button>
      </Box>

      {categoriesError && (
        <Typography color="error" sx={{ mb: 3 }}>
          Failed to load categories.
        </Typography>
      )}

      {categoryConfirmed && (
        <Box sx={{ maxWidth: 480 }}>
          {partsLoading && (
            <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
              <CircularProgress size={28} />
            </Box>
          )}

          {partsError && (
            <Typography color="error" sx={{ mb: 3 }}>
              Failed to load parts for this category.
            </Typography>
          )}

          {!partsLoading && !partsError && parts.length === 0 && (
            <Typography color="text.secondary" sx={{ mb: 3 }}>
              No parts in this category yet.
            </Typography>
          )}

          {!partsLoading && !partsError && parts.length > 0 && (
            <Autocomplete
              options={parts}
              disabled={sessionStarting}
              getOptionLabel={(option) => option.part_name}
              filterOptions={(options, { inputValue }) => {
                const input = inputValue.toLowerCase();
                return options.filter(
                  (option) =>
                    option.part_name.toLowerCase().includes(input) ||
                    option.part_code.toLowerCase().includes(input),
                );
              }}
              onChange={(e, value) => handlePartSelect(value)}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Part name or code"
                  placeholder="Type to search…"
                  InputProps={{
                    ...params.InputProps,
                    endAdornment: (
                      <>
                        {sessionStarting && <CircularProgress size={18} sx={{ mr: 1 }} />}
                        {params.InputProps.endAdornment}
                      </>
                    ),
                  }}
                />
              )}
              sx={{
                "& .MuiOutlinedInput-root": {
                  borderColor: theme.palette.divider,
                },
              }}
            />
          )}

          {sessionStartError && (
            <Typography color="error" sx={{ mt: 2 }}>
              Failed to start the session for that part — machine may not be ready. Try again.
            </Typography>
          )}
        </Box>
      )}
    </MainLayout>
  );
};

export default PartSelectionPage;
