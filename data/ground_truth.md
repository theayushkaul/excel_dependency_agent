# Ground-truth dependency edges

Column-level ground-truth dependency edges for dependency_benchmark.xlsx. Each edge means: cell/column 'to' has a formula that references 'from'. kind='indirect_unresolvable_statically' marks the one edge a purely static parser cannot recover without evaluating INDIRECT. Includes lookup_key_array edges: the MATCH() lookup array a formula searches (e.g. Products!ProductID) is a real precedent, separate from the value column it ultimately pulls (e.g. Products!UnitPrice) -- both are genuine dependencies of the same cell.

| To (dependent) | From (source) | Kind |
|---|---|---|
| Products!Margin | Products!UnitCost | same_sheet |
| Products!Margin | Products!UnitPrice | same_sheet |
| Sales!UnitPrice | Products!UnitPrice | lookup |
| Sales!UnitPrice | Sales!ProductID | same_sheet_key |
| Sales!Category | Products!Category | lookup |
| Sales!Category | Sales!ProductID | same_sheet_key |
| Sales!RegionID | Customers!RegionID | lookup |
| Sales!RegionID | Sales!CustomerID | same_sheet_key |
| Sales!TaxRate | Regions!TaxRate | lookup |
| Sales!TaxRate | Sales!RegionID | same_sheet_key |
| Sales!DiscountRate | Regions!DiscountRate | lookup |
| Sales!DiscountRate | Sales!RegionID | same_sheet_key |
| Sales!DiscountThreshold | Regions!DiscountThreshold | lookup |
| Sales!DiscountThreshold | Sales!RegionID | same_sheet_key |
| Sales!Subtotal | Sales!Quantity | same_sheet |
| Sales!Subtotal | Sales!UnitPrice | same_sheet |
| Sales!Discount | Sales!Quantity | same_sheet |
| Sales!Discount | Sales!DiscountThreshold | same_sheet |
| Sales!Discount | Sales!Subtotal | same_sheet |
| Sales!Discount | Sales!DiscountRate | same_sheet |
| Sales!TaxAmount | Sales!Subtotal | same_sheet |
| Sales!TaxAmount | Sales!Discount | same_sheet |
| Sales!TaxAmount | Sales!TaxRate | same_sheet |
| Sales!Total | Sales!Subtotal | same_sheet |
| Sales!Total | Sales!Discount | same_sheet |
| Sales!Total | Sales!TaxAmount | same_sheet |
| Summary!RevenueByCategory | Sales!Total | aggregate |
| Summary!RevenueByCategory | Sales!Category | aggregate_key |
| Summary!TotalRevenue | Summary!RevenueByCategory | same_sheet |
| Summary!RevenueByRegion | Sales!Total | aggregate |
| Summary!RevenueByRegion | Sales!RegionID | aggregate_key |
| Summary!AverageProductMargin | Products!Margin | named_range |
| Summary!AverageRegionalTaxRate | Regions!TaxRate | named_range |
| Summary!RowCountOfSelectedSheet | Summary!SelectedSheet | same_sheet |
| Summary!RowCountOfSelectedSheet | *dynamic*!column_A | indirect_unresolvable_statically |
| Sales!UnitPrice | Products!ProductID | lookup_key_array |
| Sales!Category | Products!ProductID | lookup_key_array |
| Sales!RegionID | Customers!CustomerID | lookup_key_array |
| Sales!TaxRate | Regions!RegionID | lookup_key_array |
| Sales!DiscountRate | Regions!RegionID | lookup_key_array |
| Sales!DiscountThreshold | Regions!RegionID | lookup_key_array |
