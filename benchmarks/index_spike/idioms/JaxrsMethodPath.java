import javax.ws.rs.*;

@Path("/g")
public class JaxrsMethodPath {
    @GET
    @Path("/{id}")
    public String one() {
        return "one";
    }

    @POST
    public String add() {
        return "add";
    }
}
