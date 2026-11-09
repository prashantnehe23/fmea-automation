var app = WebApplication.CreateBuilder(args).Build();
app.MapGet("/e", () => "e");
app.Run();
