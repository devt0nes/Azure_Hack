require('dotenv').config();
const app = require('./app');
const { connectMongo } = require('./config/db');

const PORT = Number(process.env.PORT || 5100);

async function bootstrap() {
    await connectMongo();
    app.listen(PORT, () => {
        console.log(`[backend] listening on http://127.0.0.1:${PORT}`);
    });
}

bootstrap().catch((err) => {
    console.error('[backend] startup failed', err);
    process.exit(1);
});
