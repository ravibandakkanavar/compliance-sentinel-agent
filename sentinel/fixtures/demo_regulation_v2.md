# Demo Data Handling Regulation

This is a synthetic regulation written for demonstrating and testing Compliance
Sentinel. It is not law and does not reproduce the text of any real regulation.

## Section 1 - Storage of credentials

A service that stores user passwords shall store them only as salted hashes produced by an algorithm designed for password storage. A service shall not store, compare or transmit a user password in plain text.

Credentials that grant a service access to another system, including API keys, database passwords and signing keys, shall not be embedded in source code or in configuration files kept under version control.

## Section 2 - Personal data in logs

A service shall not write government identifiers, dates of birth, authentication secrets or email addresses to application logs. Where a user must be identified in a log entry to investigate an incident, the entry shall carry only the internal account identifier of that user.

## Section 3 - Data minimisation at collection

A service shall collect only the personal data that is necessary for the purpose stated to the user at the point of collection. A service shall not require a government identifier or income information as a condition of creating an account unless a law obliges the service to hold that information.

## Section 4 - Consent to marketing

Consent to receive marketing communications shall be given by a clear affirmative action of the user. A consent control that is selected by default does not constitute consent.

A service shall check the recorded consent of each recipient before sending a marketing communication, and shall not send marketing communications to a user who has not consented.

## Section 5 - Erasure on request

When a user asks for their account to be deleted, the service shall erase the personal data of that user from its primary data store without undue delay. Marking a record as deleted while retaining the personal data it contains does not satisfy this section.

## Section 6 - Retention of access records

A service shall not retain records of user access, including network addresses and requested paths, for longer than ninety days. A service shall operate an automated process that deletes such records once that period has passed, and that process shall not be capable of being disabled by configuration.

## Section 7 - Transfers to third parties

A service shall transmit personal data to a third party only over an encrypted connection. A service shall not disclose the personal data of a user to a third party for advertising purposes where that user has asked the service not to sell or share their data.
