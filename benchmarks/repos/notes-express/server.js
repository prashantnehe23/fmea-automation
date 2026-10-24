const express = require("express");
const fs = require("fs");
const path = require("path");

const app = express();
const NOTES = {
  1: { owner: "ann", text: "ann's private note" },
  2: { owner: "bob", text: "bob's private note" },
};

function currentUser(req) {
  return req.get("x-user");
}

app.get("/notes/:id", (req, res) => {
  if (!currentUser(req)) return res.status(401).end();
  res.json(NOTES[req.params.id]);
});

app.get("/export", (req, res) => {
  if (!currentUser(req)) return res.status(401).end();
  const file = path.join(__dirname, "exports", req.query.name);
  res.send(fs.readFileSync(file, "utf8"));
});

app.listen(3000);
