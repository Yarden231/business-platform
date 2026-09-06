/**
 * Israeli ID checksum, mirrored from `app/domain/identifiers.py`.
 *
 * The API remains the authority. This exists so the form can fail in Hebrew
 * before a round trip, the same way password length is checked locally.
 */
const ISRAELI_ID_LENGTH = 9;

export function digitsOnly(value: string): string {
  return [...value].filter((character) => character >= '0' && character <= '9').join('');
}

export function israeliIdChecksumValid(digits: string): boolean {
  if (digits.length !== ISRAELI_ID_LENGTH || !/^\d+$/.test(digits)) {
    return false;
  }
  let total = 0;
  for (let index = 0; index < digits.length; index += 1) {
    const character = digits[index];
    if (character === undefined) {
      return false;
    }
    let step = Number(character) * (index % 2 === 0 ? 1 : 2);
    if (step > 9) {
      step -= 9;
    }
    total += step;
  }
  return total % 10 === 0;
}

export function isValidIsraeliId(raw: string): boolean {
  return israeliIdChecksumValid(digitsOnly(raw));
}
