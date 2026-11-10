const express = require("express");
const app = express();
app.get("/d", (req, res) => {
  res.send("d");
});
