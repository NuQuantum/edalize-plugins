module example_dep (
    input logic clk,
    input logic rst,
    input logic d,
    output logic [1:0] q
);

always_ff @( posedge clk, posedge rst ) begin
    if (rst)
        q <= '0;
    else
        q <= d; // this causes a linting error (WIDTHEXPAND)
end

endmodule
