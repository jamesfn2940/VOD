export default {
  async fetch(request) {
    const url = new URL(request.url);
    const fileId = url.searchParams.get("id");

    if (!fileId) {
      return new Response("Missing id parameter", { status: 400 });
    }

    const driveUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=t`;

    const response = await fetch(driveUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0",
      },
      redirect: "follow",
    });

    return new Response(response.body, {
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "video/mp4",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};
