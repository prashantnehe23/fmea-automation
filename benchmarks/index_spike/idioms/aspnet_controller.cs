using Microsoft.AspNetCore.Mvc;

[ApiController]
[Route("api/[controller]")]
public class OrdersController : ControllerBase
{
    [HttpGet("search")]
    public string Search() { return "s"; }

    [HttpGet("/absolute")]
    public string Absolute() { return "a"; }
}
