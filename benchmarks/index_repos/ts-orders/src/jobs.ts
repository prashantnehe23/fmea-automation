import { OrderService, archive } from "./service";

function nightlyCleanup() {
  new OrderService().purgeOlder(90);
  archive("exports");
}

if (require.main === module) {
  nightlyCleanup();
}
