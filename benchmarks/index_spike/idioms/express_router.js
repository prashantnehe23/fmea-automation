const express = require("express");
const app = express();
const r = express.Router();
r.get("/x", getX);
app.use("/api", r);
