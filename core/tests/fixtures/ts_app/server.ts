import { Hono } from 'hono';
import { eq, sql } from 'drizzle-orm';
import * as schema from './db/schema';

const app = new Hono();

function loadAuthor(authorId: number) {
  return app.db.select({ id: schema.users.id, email: schema.users.email })
    .from(schema.users).where(eq(schema.users.id, authorId)).limit(1);
}

app.get('/api/posts', async (c) => {
  const rows = await app.db.select().from(schema.posts).where(eq(schema.posts.published, true));
  return c.json(rows);
});

app.post('/api/posts', async (c) => {
  const author = loadAuthor(c.req.json('authorId'));
  const row = await app.db.insert(schema.posts).values({ authorId: author.id, title: 'x' });
  return c.json(row);
});

app.get('/api/users/:id', async (c) => {
  const u = await app.db.select().from(schema.users)
    .where(eq(sql`LOWER(${schema.users.username})`, c.req.param('id'))).limit(1);
  return c.json(u);
});

app.get('/api/audit', c => app.db.select({ p: schema.auditLog.payload }).from(schema.auditLog));

export default app;
