import { forward } from "@/lib/proxy";
export const dynamic = "force-dynamic";
export async function POST(request: Request) {
  const query = new URL(request.url).search;
  return forward(request, `/api/v1/replenishment/suggested-order${query}`);
}
