import { execSync } from "child_process";
import { writeFileSync } from "fs";
import { OrderRepository } from "./repository";

export class OrderService {
  private repo = new OrderRepository();

  search(term: string) {
    return this.repo.find(term);
  }

  purgeOlder(days: number) {
    return this.repo.deleteOlderThan(days);
  }
}

export class ExportService {
  exportOrder(orderId: number, path: string) {
    const data = new OrderRepository().get(orderId);
    writeFileSync(path, JSON.stringify(data));
    return path;
  }
}

export function archive(path: string) {
  execSync("tar czf " + path + ".tgz " + path);
}
