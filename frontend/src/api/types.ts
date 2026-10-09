/**
 * Typ-Helfer für das generierte OpenAPI-Schema (`schema.d.ts`, `npm run gen:api`).
 *
 * Typen werden über **Endpunkte** statt über Modellnamen abgeleitet – Backend-Modelle dürfen umbenannt
 * werden, ohne dass das Frontend bricht:
 *
 *   type Stats = Filled<ResponseOf<'/api/stats', 'get'>>
 *   type NewPart = RequestBodyOf<'/api/parts/{table}', 'post'>
 */
import type { paths } from './schema'

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'

type JsonOf<T> = T extends { content: { 'application/json': infer R } } ? R : never

type OperationOf<P extends keyof paths, M extends Method> = NonNullable<paths[P][M]>

/** JSON-Antwort (200, sonst 201) eines Endpunkts */
export type ResponseOf<P extends keyof paths, M extends Method> =
  OperationOf<P, M> extends { responses: infer Rs }
    ? Rs extends { 200: infer R }
      ? JsonOf<R>
      : Rs extends { 201: infer R }
        ? JsonOf<R>
        : never
    : never

/** JSON-Anfragekörper eines Endpunkts */
export type RequestBodyOf<P extends keyof paths, M extends Method> =
  OperationOf<P, M> extends { requestBody?: infer B } ? JsonOf<NonNullable<B>> : never

/** Query-Parameter eines Endpunkts */
export type QueryOf<P extends keyof paths, M extends Method> =
  OperationOf<P, M> extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never

/**
 * Antworten des Backends sind vollständig befüllt (Pydantic serialisiert Standardwerte mit), das Schema
 * markiert Felder mit Standardwert aber als optional. `Filled<T>` macht sie (rekursiv) verpflichtend.
 *
 * Arrays und **Tupel** bleiben erhalten (homomorphe Abbildung über `T`): `[number, number, number]` bleibt ein
 * Tupel (`StepModel.rotation`), `X[]` wird `Filled<X>[]`, `readonly` bleibt `readonly`.
 */
export type Filled<T> = T extends readonly unknown[]
  ? { [K in keyof T]: Filled<Exclude<T[K], undefined>> }
  : T extends object
    ? { [K in keyof T]-?: Filled<Exclude<T[K], undefined>> }
    : T
