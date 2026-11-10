var app = WebApplication.CreateBuilder(args).Build();
var api = app.MapGroup("/api");
api.MapGet("/x", () => "x");
api.MapPost("/y", Handlers.Create);
app.Run();
