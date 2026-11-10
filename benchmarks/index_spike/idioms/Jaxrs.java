import javax.ws.rs.*;

@Path("/g")
public class Jaxrs {
    @GET
    public String g() {
        return "g";
    }
}
