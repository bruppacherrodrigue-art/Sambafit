# Dix contrôles de swaps Solana réels

Les dix signatures ci-dessous ont été relues dans les champs RPC `preTokenBalances`, `postTokenBalances`, `accountKeys`, `fee`, `innerInstructions` et `instructions`. Les deltas ont été recalculés par propriétaire sans employer `SolanaDecoder._balances`. Les discriminants DLMM proviennent de l’[IDL officiel Meteora](https://github.com/MeteoraAg/dlmm-sdk/blob/main/idls/dlmm.json) v0.12.0 (SHA-256 `045c0f4af044be046b6a14b350077e4242e8ac026b64a855803dab30fcdd8b35`). Toutes les sommes sont en unités de base, sans valorisation USD inventée.

| Signature | Propriétaire signataire / payeur | Deltas propriétaire (base) | Swap DLMM | Frais lamports | Concordance |
|---|---|---|---:|---:|---|
| `5a6MpzMXHW4McZdrWt1b1bhQJY5Psdn9xofuaF42MVGhpU2e7LXrAybN552nfnKevUn5aCgzFkZrcNJ8Yp7iAsmE` | oui / oui | JUPyiwrY… +271452511 (d=6)<br>So111111… -784506780 (d=9) | 1 | 5000 | oui |
| `3iEGPkdRQCETdiFYxyD4Wm1YdoWJEowpNAZ67MJrU6kiSKG2CrMDz1hea4FgpfZgqVek77DSA4fE4bTs4Q5oJtek` | oui / oui | EPjFWdd5… -133180798 (d=6)<br>JUPyiwrY… +382638749 (d=6) | 1 | 5139 | oui |
| `8bqJC4NAFqNL9FECWZNicQskBweCib9vq5pidQZAPZKd53eRpLmXJMdexw1h3WYMtPX3QWzkZnpCLcu8SBCRw5T` | oui / oui | 6GmAFSYs… +179161097941 (d=9)<br>EPjFWdd5… -49998792 (d=6) | 1 | 5000 | oui |
| `5Mz1Q2Xi2Uh8nPFM9k6z34XhpDmFpR9eUjMr8feHu5Azun6vWtZxskdYkKMBtMS5qVaBHnRgRikq21ved8ZTfaYC` | oui / oui | EPjFWdd5… -10114032 (d=6)<br>HSUMi4rM… +11325236488 (d=6) | 1 | 6216 | oui |
| `4PT85QjozHxG4aZbhBS77PhAuzGB2xy644MXcsbMWtCM2HsAXQ2TFDVNf9PvwGqrzdz3Mczq9s8yFbPG5a9Mxj1A` | oui / oui | EPjFWdd5… -6679775 (d=6)<br>So111111… +55506902 (d=9) | 1 | 5001 | oui |
| `2jehsSszmEaUpnwaYjThBfAshEenqN6NqeqnTa2sutQnsTj2SQcTFvwhf3c2Zg3mf1veP36zKrN2znvkAda4DcgJ` | oui / oui | EPjFWdd5… -266431553 (d=6)<br>JUPyiwrY… +765478494 (d=6) | 1 | 5318 | oui |
| `5SrCCwkftz8QfqWq3ZjW1RNJk6hM4j5U29tAonCAu1cqx11ygGp98fJVG5ZTt3wnwvEiThRyLi6jAS6NvxRf5ALr` | oui / oui | JUPyiwrY… +633726465 (d=6)<br>So111111… -1831636727 (d=9) | 1 | 5000 | oui |
| `5KgGTEjrjg6JHPeTwggU6ziQJiW7HREKEiczBhBvXwYXaHFL6KkiVubAyVvvyhDV5Cduoh6Dz5Y87C9Dhpd2jjQB` | oui / oui | JUPyiwrY… +545099221 (d=6)<br>So111111… -1575480604 (d=9) | 1 | 5000 | oui |
| `3VXcDFCBKCj6ngZHcWDedu2yX7MWHEC1qRQt7JNBMjLzdwxGMAPMkYqU8bGH3nwZUARRuNhVbY8rczGfME8zmdXY` | oui / oui | JUPyiwrY… +3066947150 (d=6)<br>So111111… -8864286643 (d=9) | 1 | 5000 | oui |
| `5WPg66xjUJ4xM7w6GEEQH21ziPYpoPo4cp4BrsacaX4QM1QUzkpqFzvzZwqi6NuVJe3hrYHQcYS5wzpSzK9izVGz` | oui / oui | JUPyiwrY… +504832825 (d=6)<br>So111111… -1459100094 (d=9) | 1 | 5000 | oui |

Chaque ligne a un seul discriminant de swap DLMM et exactement deux variations nettes SPL attribuables au propriétaire signataire. Les transactions ayant plusieurs swaps internes sont **quarantinées** (`partial_route`) et ne figurent pas parmi ces dix validations. Le fournisseur peut décrire une étape du pool plutôt que le trajet entier du signataire. Le payeur de frais et le propriétaire restent des rôles distincts, même quand leurs adresses coïncident dans ces dix lignes. Ces contrôles ne reconstituent pas les comptes SPL fermés ni le SOL natif pour les transactions partielles.

Corpus complet, programmes, rôles, hashes et statuts : `data/real-pilot-20260926/manifest.json` et `verification.json`.
