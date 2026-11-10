import org.springframework.web.bind.annotation.*;

@RestController
public class SpringMapping {
    @RequestMapping(value = "/f", method = RequestMethod.POST)
    public String f() {
        return "f";
    }
}
