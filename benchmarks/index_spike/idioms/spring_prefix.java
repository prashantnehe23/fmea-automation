import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class SpringPrefix {
    @GetMapping("/items")
    public String items() {
        return "items";
    }

    @PostMapping
    public String create() {
        return "create";
    }
}
