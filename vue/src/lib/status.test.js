import assert from "node:assert/strict";
import { test } from "node:test";

import { woStatusClass, woStatusId } from "./status.js";

test("woStatusId maps every server status to the operator vocabulary", () => {
	assert.equal(woStatusId("Not Started"), "Belum Mulai");
	assert.equal(woStatusId("In Process"), "Berjalan");
	assert.equal(woStatusId("Stopped"), "Dihentikan");
	assert.equal(woStatusId("Closed"), "Ditutup");
	assert.equal(woStatusId("Completed"), "Selesai");
	assert.equal(woStatusId("Stock Reserved"), "Reservasi Stok");
	assert.equal(woStatusId("Stock Partially Reserved"), "Reservasi Stok");
	assert.equal(woStatusId("Cancelled"), "Dibatalkan");
	assert.equal(woStatusId("Submitted"), "Disetujui");
	assert.equal(woStatusId("Draft"), "Draft");
});

test("woStatusId passes unknown/empty values through", () => {
	assert.equal(woStatusId("Some Future Status"), "Some Future Status");
	assert.equal(woStatusId(undefined), "");
});

test("woStatusClass colors stopped amber, finished green, rest neutral", () => {
	assert.match(woStatusClass("Stopped"), /amber/);
	assert.match(woStatusClass("Completed"), /green/);
	assert.match(woStatusClass("In Process"), /gray/);
});
